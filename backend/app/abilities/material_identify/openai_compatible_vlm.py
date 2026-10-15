"""OpenAI 兼容协议的视觉语言模型（VLM）材质识别 —— 输出「材质卡片」。

同一份代码可指向：阿里云 MaaS（`qwen3-vl-plus`）、OpenAI 官方（`gpt-4o`）、
或任何 OpenAI 兼容中转 —— 只需改 `base_url` / `model` / `api_key`。

识别结果不是「材质 tag 列表」，而是 MVP 计划 §3.1 的材质卡片：
逐区域的 A 层视觉属性（颜色 / 图案 / 光泽）+ B/C 层占位字段 + 逐字段置信度，
外加一小块「材质小样」（swatch）字节 —— 它是生成阶段的保真锚点。

阿里 MaaS 实测要点：
  - `POST {base}/chat/completions`，content 用标准多模态数组
  - `response_format={"type":"json_object"}` 可用
  - `usage.prompt_tokens_details.image_tokens` 反映图片开销
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.abilities.base import MaterialCardResult
from app.abilities.http import ProviderError, RetryingHttpClient
from app.abilities.image_ops import DEFAULT_SWATCH_MAX_SIDE, prepare_vision_image
from app.abilities.material_identify.card_normalize import attach_swatch, normalize_card
from app.taxonomy import material_labels

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"[\[{].*[\]}]", re.DOTALL)

SYSTEM_PROMPT = """你是一名资深服装面料分析专家。
分析服装图片，输出一张结构化的**材质卡片**。

规则：
1. 只描述你**看得见**的视觉属性，不要编造物理参数。
2. color.dominant.hex 必须是 6 位十六进制（形如 "#2B3A4A"）；
   palette 至少 2 项、ratio 之和为 1。
3. pattern.type 只能是：纯色 / 条纹 / 格纹 / 碎花 / 定位印花。
4. optical.gloss 只能是：哑光 / 微光 / 缎面 / 金属光；
   optical.transparency 只能是：不透明 / 半透明 / 透明。
5. fabric.material 只能从给定受控词表中选，不得自创、改写或加后缀；
   拿不准时选最接近的一个并降低 confidence。
6. behavior.weight（轻薄/中等/厚重）与 behavior.drape（挺括/适中/垂坠）为可选，
   只有看得准才填。
7. confidence 是 0-1 的置信度，逐字段给出（color / pattern / gloss）。
   单张图难以区分的相似材质（如桑蚕丝 vs 醋酸 vs 缎面涤纶）不要给过高置信度。
8. evidence 必须是**视觉依据**：光泽强弱、织纹/纹理、透视度、挺括度，
   一句话说清"为什么是这个判断"。
9. swatch_box 是一块**平坦、干净、无褶皱与阴影**的面料区域的归一化坐标
   [left, top, right, bottom]，取值 0~1；确实找不到合适区域时给 null。
10. category 只能是：女装上衣 / 连衣裙；判断不了时给最接近的一个。

只输出 JSON，不要解释文字，不要 Markdown 代码块。格式：
{"category":"连衣裙",
 "color":{"dominant":{"hex":"#2B3A4A","name":"深灰蓝","lab":[35,-2,-12]},
          "palette":[{"hex":"#2B3A4A","ratio":0.72},{"hex":"#C8C2B8","ratio":0.28}],
          "distribution":"整体均匀"},
 "pattern":{"type":"纯色","scale":null,"direction":null,"layout":"全身"},
 "optical":{"gloss":"哑光","transparency":"不透明"},
 "fabric":{"material":"棉","material_en":"Cotton","confidence":0.72},
 "behavior":{"weight":"中等","drape":"适中"},
 "confidence":{"color":0.95,"pattern":0.9,"gloss":0.8},
 "evidence":"表面哑光无反射、织纹细密均匀，垂坠适中，符合棉质平纹特征。",
 "swatch_box":[0.3,0.4,0.6,0.7]}"""

USER_PROMPT = """分析这张服装图片，输出材质卡片 JSON。
fabric.material 只能从以下受控词表中选择（都不像时选最接近的一个）：
{taxonomy}"""


def _extract_json(text: str) -> Any:
    """从模型输出里提取 JSON：优先整体解析，失败则剥围栏、再兜底取首个 JSON 块。"""
    cleaned = _FENCE_RE.sub("", (text or "").strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        pass

    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass

    raise ProviderError(f"模型未返回可解析的 JSON: {cleaned[:200]!r}", provider="VLM")


class OpenAICompatibleVLMIdentifier:
    name = "openai_compatible"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "qwen3-vl-plus",
        *,
        swatch_enabled: bool = True,
        swatch_max_side: int = DEFAULT_SWATCH_MAX_SIDE,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        vision_max_side: int = 1568,
        http_client: RetryingHttpClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.swatch_enabled = swatch_enabled
        self.swatch_max_side = swatch_max_side
        self.vision_max_side = vision_max_side
        #: 最近一次调用的 token 用量，供编排器记录
        self.last_usage: dict[str, Any] | None = None

        self._http = http_client or RetryingHttpClient(
            provider=f"VLM({model})", timeout_s=timeout_s, max_retries=max_retries
        )

        #: 注入 prompt 的受控词表清单（与 taxonomy 单例共享缓存）
        self._label_list = material_labels()

    # ------------------------------------------------------------------ #
    # MaterialIdentifier 协议
    # ------------------------------------------------------------------ #
    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> MaterialCardResult:
        image_ref = self._image_reference(image_bytes, image_url)
        payload = self._build_payload(image_ref, context_title)

        response = self._post(payload)
        self.last_usage = response.get("usage") or None

        content = self._extract_content(response)
        card = normalize_card(_extract_json(content))
        self._attach_swatch(card, image_bytes)
        return card

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _image_reference(self, image_bytes: bytes | None, image_url: str) -> str:
        if image_bytes:
            # 必须用 data URL：外部服务访问不到我们的 localhost /media 地址
            _, _, data_url = prepare_vision_image(
                image_bytes, max_side=self.vision_max_side
            )
            return data_url
        if image_url.startswith(("http://", "https://")):
            return image_url  # 公网地址交给模型侧抓取
        raise ProviderError(
            "缺少图片数据：既没有 image_bytes，也没有可用的 image_url",
            provider=f"VLM({self.model})",
        )

    def _build_payload(self, image_ref: str, context_title: str) -> dict[str, Any]:
        user_text = USER_PROMPT.format(taxonomy=self._label_list)
        if context_title:
            user_text += f"\n\n（图片来源标题，仅供参考：{context_title}）"

        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_ref}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 1200,
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        body = dict(payload)
        body["response_format"] = {"type": "json_object"}
        return self._http.post_json(url, body, headers=headers)

    def _extract_content(self, response: dict[str, Any]) -> str:
        choices = response.get("choices") or []
        if not choices:
            raise ProviderError(
                f"响应中没有 choices: {str(response)[:200]}",
                provider=f"VLM({self.model})",
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # 少数端点返回分段数组
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        return content or ""

    def _attach_swatch(
        self, card: MaterialCardResult, image_bytes: bytes | None
    ) -> None:
        """按模型给的框裁出材质小样（细节见 `card_normalize.attach_swatch`）。"""
        if not self.swatch_enabled:
            return
        attach_swatch(card, image_bytes, max_side=self.swatch_max_side)

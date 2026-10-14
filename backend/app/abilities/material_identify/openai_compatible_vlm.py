"""OpenAI 兼容协议的视觉语言模型（VLM）材质识别。

同一份代码可指向：阿里云 MaaS（`qwen3-vl-plus`）、OpenAI 官方（`gpt-4o`）、
或任何 OpenAI 兼容中转 —— 只需改 `base_url` / `model` / `api_key`。

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

from app.abilities.base import MaterialTagResult
from app.abilities.http import ProviderError, RetryingHttpClient
from app.abilities.image_ops import prepare_vision_image
from app.taxonomy import load_taxonomy

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"[\[{].*[\]}]", re.DOTALL)

SYSTEM_PROMPT = """你是一名资深服装面料分析专家。
分析服装图片，反推其可能的**面料材质**，并给出可能度与判断依据。

规则：
1. material 只能从下面给出的受控词表中选择，不得自创、改写或加后缀。
2. 若为拼接/多层次（主体+袖口+内衬等），分别列出并按可能度降序。
3. confidence 是 0-1 的可能度。单张图难以区分的相似材质
   （如桑蚕丝 vs 醋酸 vs 缎面涤纶）不要给过高置信度。
4. evidence 必须是**视觉依据**：光泽强弱、垂坠感、织纹/纹理、透视度、挺括度，
   一句话说清"为什么像这个材质"。
5. 最多输出 {top_k} 个候选。

只输出 JSON，不要解释文字，不要 Markdown 代码块。格式：
{{"tags":[{{"material":"桑蚕丝","material_en":"Mulberry Silk","confidence":0.82,"evidence":"..."}}]}}"""

USER_PROMPT = """分析这张服装图片的面料材质。只能从以下受控词表中选择 material：
{taxonomy}

按可能度从高到低输出 JSON。"""


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


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
    name = "maas"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "qwen3-vl-plus",
        *,
        top_k: int = 4,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        vision_max_side: int = 1568,
        http_client: RetryingHttpClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.top_k = max(1, top_k)
        self.vision_max_side = vision_max_side
        #: 最近一次调用的 token 用量，供编排器记录
        self.last_usage: dict[str, Any] | None = None

        self._http = http_client or RetryingHttpClient(
            provider=f"VLM({model})", timeout_s=timeout_s, max_retries=max_retries
        )

        taxonomy = load_taxonomy()
        self._by_zh = {item["material"]: item for item in taxonomy}
        self._by_en = {
            str(item.get("material_en", "")).lower(): item for item in taxonomy
        }
        self._label_list = "、".join(
            f"{item['material']}({item.get('material_en', '')})" for item in taxonomy
        )

    # ------------------------------------------------------------------ #
    # MaterialIdentifier 协议
    # ------------------------------------------------------------------ #
    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> list[MaterialTagResult]:
        image_ref = self._image_reference(image_bytes, image_url)
        payload = self._build_payload(image_ref, context_title)

        response = self._post(payload)
        self.last_usage = response.get("usage") or None

        content = self._extract_content(response)
        return self._normalize(_extract_json(content))

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
                {"role": "system", "content": SYSTEM_PROMPT.format(top_k=self.top_k)},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_ref}},
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 900,
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

    def _normalize(self, raw: Any) -> list[MaterialTagResult]:
        items = raw.get("tags") if isinstance(raw, dict) else raw
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ProviderError(
                f"模型输出的 JSON 结构不符合预期: {str(raw)[:200]}",
                provider=f"VLM({self.model})",
            )

        best: dict[str, MaterialTagResult] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_name = str(
                item.get("material") or item.get("material_en") or ""
            ).strip()
            if not raw_name:
                continue

            definition = self._match(raw_name, item.get("material_en"))
            material = definition["material"] if definition else raw_name
            if definition is None:
                logger.warning("材质 tag 不在受控词表内，原样保留: %r", raw_name)

            candidate = MaterialTagResult(
                material=material,
                material_en=(definition or {}).get("material_en")
                or str(item.get("material_en") or ""),
                confidence=_clamp_confidence(item.get("confidence")),
                evidence=str(item.get("evidence") or "").strip(),
                category=(definition or {}).get("category", ""),
                rank=0,
            )
            existing = best.get(material)
            if existing is None or candidate.confidence > existing.confidence:
                best[material] = candidate

        ordered = sorted(best.values(), key=lambda tag: tag.confidence, reverse=True)[
            : self.top_k
        ]
        for index, tag in enumerate(ordered):
            tag.rank = index
        return ordered

    def _match(self, name: str, material_en: Any = None) -> dict | None:
        """把模型输出的名字归一化回受控词表条目。"""
        if name in self._by_zh:
            return self._by_zh[name]

        for candidate in (name, str(material_en or "")):
            key = candidate.strip().lower()
            if key and key in self._by_en:
                return self._by_en[key]

        # 去掉空白/连字符后再比（"mulberry silk" ≈ "Mulberry-Silk"）
        compact = re.sub(r"[\s\-_]+", "", name.lower())
        if compact:
            for english, definition in self._by_en.items():
                if re.sub(r"[\s\-_]+", "", english) == compact:
                    return definition
        return None

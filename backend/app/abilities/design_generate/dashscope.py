"""阿里云 MaaS 生图（OpenAI 兼容 `/images/generations`）—— qwen-image 系列。

实测要点（qwen-image-3.0）：
  - `size` 必须形如 `"1024x1024"`；写成 `"1024*1024"` 会直接 400
  - `image` 支持字符串或数组，**数组即多参考图**；
    但模型限 **0~3 张**（0=文生图，1~3=图生图），超过会直接 400
  - 响应 `data` 是**被转义的 JSON 字符串数组**，必须逐个 `json.loads`
  - 返回的是 OSS 临时地址 → 编排器必须镜像落盘，否则会静默失效
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.abilities.base import DesignImageResult, MaterialImageResult, ReferenceImage
from app.abilities.http import ProviderError, RetryingHttpClient
from app.abilities.image_ops import reference_data_url
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt

logger = logging.getLogger(__name__)

_SIZE_RE = re.compile(r"^\d+x\d+$")


def _is_public_url(url: str) -> bool:
    """本机地址外部服务访问不到，不能直接作为参考图传出去。"""
    if not url.startswith(("http://", "https://")):
        return False
    lowered = url.lower()
    return (
        "localhost" not in lowered
        and "127.0.0.1" not in lowered
        and "[::1]" not in lowered
    )


def _extract_urls(response: dict[str, Any]) -> list[str]:
    """从生图响应里取出图片 URL。

    兼容两种形态：
      1. `{"data": ["{\\"url\\": \\"https://...\\"}"]}`  ← 阿里 MaaS 的实际形态
      2. `{"data": [{"url": "https://..."}]}`
      3. `{"output": {"choices": [{"message": {"content": [{"image": "..."}]}}]}}`
    """
    urls: list[str] = []

    data = response.get("data")
    if isinstance(data, list):
        for item in data:
            parsed: Any = item
            if isinstance(parsed, str):
                if parsed.startswith("http"):
                    urls.append(parsed)
                    continue
                try:
                    parsed = json.loads(parsed)
                except ValueError:
                    logger.warning("无法解析生图响应条目: %r", parsed[:120])
                    continue
            if isinstance(parsed, dict):
                url = parsed.get("url")
                if isinstance(url, str) and url:
                    urls.append(url)

    if not urls:  # 兜底：多模态 output 形态
        output = response.get("output") or {}
        for choice in output.get("choices") or []:
            message = choice.get("message") or {}
            for part in message.get("content") or []:
                if isinstance(part, dict) and isinstance(part.get("image"), str):
                    urls.append(part["image"])

    return urls


class QwenImageGenerator:
    name = "dashscope"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str = "qwen-image-3.0",
        *,
        size: str = "1024x1024",
        max_refs: int = 4,
        prompt_extend: bool = False,
        reference_max_side: int = 1024,
        timeout_s: float = 180.0,
        max_retries: int = 2,
        http_client: RetryingHttpClient | None = None,
    ) -> None:
        if not _SIZE_RE.match(size):
            raise ValueError(
                f"image_size 必须形如 '1024x1024'（用 x 分隔），收到: {size!r}"
            )

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.size = size
        self.max_refs = max(1, max_refs)
        self.prompt_extend = prompt_extend
        self.reference_max_side = reference_max_side
        #: 最近一次调用的用量，供编排器记录
        self.last_usage: dict[str, Any] | None = None

        self._http = http_client or RetryingHttpClient(
            provider=f"生图({model})", timeout_s=timeout_s, max_retries=max_retries
        )

    # ------------------------------------------------------------------ #
    # DesignImageGenerator 协议
    # ------------------------------------------------------------------ #
    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
    ) -> list[DesignImageResult]:
        prompt = build_design_prompt(
            material_tags=[m.tag for m in material_images],
            material_images_count=len(material_images),
            design_idea=design_idea,
            has_reference=reference is not None,
        )

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": max(1, num_candidates),
            "size": self.size,
            "negative_prompt": NEGATIVE_PROMPT,
            # 关掉提示词改写：我们的指令已经是结构化组装好的，不希望被模型重写
            "prompt_extend": self.prompt_extend,
        }
        image_field = self._build_image_field(material_images, reference)
        if image_field is not None:
            payload["image"] = image_field

        response = self._post(payload)
        self.last_usage = response.get("usage") or None

        urls = _extract_urls(response)
        if not urls:
            raise ProviderError(
                f"生图响应中没有图片 URL: {str(response)[:300]}",
                provider=f"生图({self.model})",
            )

        return [
            DesignImageResult(
                external_url=url,
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                model=self.model,
                seed=0,
                is_mock=False,
                rank=index,
            )
            for index, url in enumerate(urls)
        ]

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _build_image_field(
        self,
        material_images: list[MaterialImageResult],
        reference: ReferenceImage | None,
    ) -> str | list[str] | None:
        refs: list[str] = []

        if reference is not None:
            value = self._as_reference(
                reference.image_bytes, reference.external_url, "原服装图"
            )
            if value:
                refs.append(value)

        for image in self._pick_material_refs(material_images):
            value = self._as_reference(
                image.image_bytes, image.external_url, f"材质图({image.tag})"
            )
            if value:
                refs.append(value)

        if not refs:
            return None  # 退化为纯文生图

        if len(refs) > self.max_refs:
            logger.warning(
                "参考图 %d 张超过上限 %d，已截断（优先保留原服装图与靠前的材质图）",
                len(refs),
                self.max_refs,
            )
            refs = refs[: self.max_refs]

        return refs[0] if len(refs) == 1 else refs

    @staticmethod
    def _pick_material_refs(
        material_images: list[MaterialImageResult],
    ) -> list[MaterialImageResult]:
        """每个材质 tag 只留相似度最高的一张，再按相似度降序。

        否则同一个 tag 的多张图会占满有限的参考位，其它材质反而进不来。
        """
        best_per_tag: dict[str, MaterialImageResult] = {}
        for image in material_images:
            current = best_per_tag.get(image.tag)
            if current is None or image.similarity > current.similarity:
                best_per_tag[image.tag] = image
        return sorted(
            best_per_tag.values(), key=lambda item: item.similarity, reverse=True
        )

    def _as_reference(
        self, image_bytes: bytes | None, external_url: str, label: str
    ) -> str | None:
        if image_bytes:
            return reference_data_url(image_bytes, max_side=self.reference_max_side)
        url = (external_url or "").strip()
        if _is_public_url(url):
            return url
        if url:
            logger.warning(
                "%s 是本机地址，外部服务访问不到，已跳过: %s", label, url[:80]
            )
        return None

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/images/generations"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        return self._http.post_json(url, payload, headers=headers)

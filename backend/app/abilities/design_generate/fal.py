"""真实图生图（fal.ai / Replicate）—— 占位实现。

接入方式（见设计方案 §2.4）：经 fal.ai / Replicate 聚合接入
Nano Banana 2 / FLUX.2 Kontext / Seedream 等指令式图像编辑模型，
支持多参考图输入（原服装图 + 材质图）与编辑链迭代。
"""

from __future__ import annotations

from app.abilities.base import DesignImageResult, MaterialImageResult, ReferenceImage
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt


class FalDesignGenerator:
    name = "fal"

    def __init__(self, api_key: str = "", model: str = "fal-ai/nano-banana/edit") -> None:
        self.api_key = api_key
        self.model = model

    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
    ) -> list[DesignImageResult]:
        # TODO:
        #   prompt = build_design_prompt(...)
        #   image_urls = [reference.external_url] + [m.external_url for m in material_images]
        #   fal_client.subscribe(self.model, arguments={"prompt": prompt,
        #       "image_urls": image_urls, "num_images": num_candidates,
        #       "negative_prompt": NEGATIVE_PROMPT})
        #   -> DesignImageResult(external_url=..., model=self.model, is_mock=False)
        raise NotImplementedError(
            "FalDesignGenerator 尚未实现，请设置 PROVIDER_MODE=mock 或补全实现。"
        )


def prompt_preview(
    material_images: list[MaterialImageResult], design_idea: str, has_reference: bool
) -> str:
    return build_design_prompt(
        material_tags=[m.tag for m in material_images],
        material_images_count=len(material_images),
        design_idea=design_idea,
        has_reference=has_reference,
    )

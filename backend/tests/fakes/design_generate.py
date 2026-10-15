"""Fake 图生图：确定性生成设计图候选，并输出真实组装好的 prompt（仅供测试）。"""

from __future__ import annotations

import hashlib

from app.abilities.base import DesignImageResult, MaterialImageResult, ReferenceImage
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt

from fakes.placeholder_images import KIND_DESIGN, make_image


class FakeDesignGenerator:
    name = "fake"

    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
        material_summary: str = "",
    ) -> list[DesignImageResult]:
        labels = sorted({m.label for m in material_images if m.label})
        ref_digest = ""
        if reference is not None:
            payload = reference.image_bytes or reference.external_url.encode("utf-8")
            ref_digest = hashlib.sha256(payload or b"").hexdigest()[:12]

        prompt = build_design_prompt(
            material_summary=material_summary,
            material_images_count=len(material_images),
            design_idea=design_idea,
            has_reference=reference is not None,
        )

        results: list[DesignImageResult] = []
        for i in range(max(1, num_candidates)):
            seed_str = f"design|{design_idea}|{'|'.join(labels)}|{ref_digest}|{i}"
            data = make_image(
                seed=seed_str,
                label=f"DESIGN {i + 1:02d}",
                kind=KIND_DESIGN,
            )
            results.append(
                DesignImageResult(
                    content_type="image/png",
                    image_bytes=data,
                    prompt=prompt,
                    negative_prompt=NEGATIVE_PROMPT,
                    model="fake-diffusion-v1",
                    seed=int(
                        hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8], 16
                    ),
                    rank=i,
                    used_reference=reference is not None,
                )
            )
        return results

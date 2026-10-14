"""Mock 图生图：确定性生成设计图候选，并输出真实组装好的 prompt。"""

from __future__ import annotations

import hashlib

from app.abilities.base import DesignImageResult, MaterialImageResult, ReferenceImage
from app.abilities.mock_images import KIND_DESIGN, make_image
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt


class MockDesignGenerator:
    name = "mock"

    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
    ) -> list[DesignImageResult]:
        tags = sorted({m.tag for m in material_images if m.tag})
        ref_digest = ""
        if reference is not None:
            payload = reference.image_bytes or reference.external_url.encode("utf-8")
            ref_digest = hashlib.sha256(payload or b"").hexdigest()[:12]

        prompt = build_design_prompt(
            material_tags=tags,
            material_images_count=len(material_images),
            design_idea=design_idea,
            has_reference=reference is not None,
        )

        results: list[DesignImageResult] = []
        for i in range(max(1, num_candidates)):
            seed_str = f"design|{design_idea}|{'|'.join(tags)}|{ref_digest}|{i}"
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
                    model="mock-diffusion-v1",
                    seed=int(hashlib.sha256(seed_str.encode("utf-8")).hexdigest()[:8], 16),
                    is_mock=True,
                    rank=i,
                )
            )
        return results

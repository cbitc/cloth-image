"""Fake 材质图检索：按 tag 确定性生成面料小样图（仅供测试）。"""

from __future__ import annotations

from urllib.parse import quote

from app.abilities.base import MaterialImageResult, MaterialTagResult
from app.taxonomy import build_material_query_zh

from fakes.placeholder_images import KIND_MATERIAL, make_image


class FakeMaterialImageSearchProvider:
    name = "fake"

    def search(
        self, tags: list[MaterialTagResult], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        results: list[MaterialImageResult] = []
        rank = 0
        for tag in tags:
            label = (tag.material_en or tag.material).upper()
            for j in range(per_tag):
                seed = f"material|{tag.material}|{j}"
                data = make_image(
                    seed=seed,
                    label=f"{label} SWATCH {j + 1}",
                    kind=KIND_MATERIAL,
                )
                results.append(
                    MaterialImageResult(
                        tag=tag.material,
                        similarity=round(
                            max(0.35, 0.96 - 0.05 * j - 0.02 * tag.rank), 2
                        ),
                        content_type="image/png",
                        image_bytes=data,
                        source_url=(
                            "https://fabric-library.example.com/search?q="
                            + quote(build_material_query_zh(tag.material))
                        ),
                        rank=rank,
                    )
                )
                rank += 1
        return results

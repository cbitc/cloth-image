"""Mock 服装图搜索：确定性生成占位服装图，无需网络。"""

from __future__ import annotations

from app.abilities.base import ClothingImageResult
from app.abilities.mock_images import KIND_CLOTHING, make_image

DEFAULT_SITES = ["mock-shop", "mock-lookbook"]


class MockClothingSearchProvider:
    name = "mock"

    def search(
        self, sites: list[str], query: str, count: int
    ) -> list[ClothingImageResult]:
        sites = [s for s in (sites or []) if s] or DEFAULT_SITES
        query = (query or "").strip()
        results: list[ClothingImageResult] = []
        for i in range(count):
            site = sites[i % len(sites)]
            seed = f"clothing|{query}|{site}|{i}"
            data = make_image(
                seed=seed,
                label=f"LOOK {i + 1:02d}",
                kind=KIND_CLOTHING,
                footer=f"{site} | {query or 'apparel'}",
            )
            results.append(
                ClothingImageResult(
                    provider="mock",
                    content_type="image/png",
                    image_bytes=data,
                    page_url=f"https://example.com/{site}/look/{i + 1}",
                    title=f"{query or '服装'} 参考款 {i + 1}",
                    site=site,
                    source_query=query,
                )
            )
        return results

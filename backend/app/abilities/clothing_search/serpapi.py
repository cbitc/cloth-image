"""真实服装图搜索（SerpAPI / 图库 API）—— 占位实现。

接入方式（见设计方案 §2.1）：
  - 用 SerpAPI 的 google_images / bing_images engine，
    query 加 `site:{domain}` 限定目标网站；
  - 或接 Unsplash / Pexels 官方 API（合规、结构化）；
  - 只需返回 ClothingImageResult 列表；若返回 external_url，
    编排器会自动镜像到对象存储。
"""

from __future__ import annotations

from app.abilities.base import ClothingImageResult


class SerpApiClothingSearchProvider:
    name = "serpapi"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def search(
        self, sites: list[str], query: str, count: int
    ) -> list[ClothingImageResult]:
        # TODO: 接入 SerpAPI
        #   params = {"engine": "google_images", "q": _with_site(query, sites),
        #             "num": count, "api_key": self.api_key}
        #   -> 解析 images_results -> ClothingImageResult(external_url=..., page_url=...)
        raise NotImplementedError(
            "SerpApiClothingSearchProvider 尚未实现，请设置 PROVIDER_MODE=mock 或补全实现。"
        )

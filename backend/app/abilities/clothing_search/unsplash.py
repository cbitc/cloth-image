"""Unsplash 服装图搜索（真实实现）。

官方契约（https://unsplash.com/documentation#search-photos）::

    GET https://api.unsplash.com/search/photos?query=...&per_page=30&page=1
    Authorization: Client-ID <Access Key>

要点：
- **只需要 Access Key**（Secret Key 仅用于 OAuth 授权用户，图片搜索用不到）。
- Unsplash **不支持按站点过滤**，`sites` 参数被忽略。
- 官方要求**热链**（直接用 `urls.*`）并标注摄影师与 Unsplash：摄影师写进 `title`、
  原图页写进 `page_url`；图片本身仍由编排器镜像落盘。
- demo 应用限 **50 次/小时**，限额状态见响应头 `X-Ratelimit-Remaining`。

请求 / 鉴权 / 分页 / 解析统一在 `app/abilities/unsplash_client.py`（与材质图检索共用）。
"""

from __future__ import annotations

from app.abilities.base import ClothingImageResult
from app.abilities.http import RetryingHttpClient
from app.abilities.unsplash_client import (
    DEFAULT_BASE_URL,
    UnsplashClient,
    credit,
)

#: 兜底：查询为空时用这个词，避免 400
DEFAULT_QUERY = "fashion clothing"
#: 单次搜索最多取回多少张（搜索页 count 上限 60）
MAX_COUNT = 60


class UnsplashClothingSearchProvider:
    name = "unsplash"
    #: 供 /api/search/sites 展示；Unsplash 不支持站点过滤，仅一个说明项
    sites = [{"id": "unsplash", "label": "Unsplash（不限站点）"}]

    def __init__(
        self,
        access_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        http_client: RetryingHttpClient | None = None,
    ) -> None:
        self._client = UnsplashClient(
            access_key,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            http_client=http_client,
        )

    # ------------------------------------------------------------------ #
    # ClothingSearchProvider 协议
    # ------------------------------------------------------------------ #
    def search(
        self, sites: list[str], query: str, count: int
    ) -> list[ClothingImageResult]:
        """按关键词搜服装图。`sites` 被忽略（Unsplash 无站点过滤）。"""
        self._client.require_key("搜索服装图")

        query = (query or "").strip() or DEFAULT_QUERY
        want = max(1, min(count or 1, MAX_COUNT))

        return [
            ClothingImageResult(
                provider=self.name,
                content_type="image/jpeg",
                external_url=photo.image_url,
                page_url=photo.page_url,
                title=credit(photo.author, photo.description),
                site="unsplash",
                source_query=query,
            )
            for photo in self._client.search(query, want)
        ]

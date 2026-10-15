"""Unsplash 公共客户端：鉴权、分页、结果归一化。

`/search/photos` 的请求、鉴权、翻页与解析在「服装图」「材质图」两个能力里完全一致，
抽到这里避免两份实现漂移。

官方要点（https://unsplash.com/documentation#search-photos）：
- 只需 **Access Key**：`Authorization: Client-ID <key>`（Secret Key 仅用于 OAuth）
- 单页最多 30 条；需要的数量超过 30 会自动翻页
- 返回的 `urls.*` 要求**热链**，并标注摄影师 + Unsplash
- demo 应用限 50 次/小时（响应头 `X-Ratelimit-Remaining`）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from app.abilities.http import ProviderAuthError, RetryingHttpClient

#: 单页上限
MAX_PER_PAGE = 30
#: 最多翻几页（防护，避免异常响应导致无限翻页）
MAX_PAGES = 3

DEFAULT_BASE_URL = "https://api.unsplash.com"


@dataclass(slots=True)
class UnsplashPhoto:
    """归一化后的一张 Unsplash 照片。"""

    #: `urls.regular`（官方要求直接使用该地址，即热链）
    image_url: str
    #: `urls.small` 等小图地址：只用于本地颜色分析，不对外展示（能省带宽）
    thumb_url: str = ""
    #: `links.html`，原始照片页，用于署名跳转
    page_url: str = ""
    author: str = ""
    description: str = ""


def credit(author: str, description: str = "") -> str:
    """按官方要求拼接「描述 + Photo by X on Unsplash」。"""
    author = (author or "").strip()
    description = (description or "").strip()
    if description and author:
        return f"{description} · Photo by {author} on Unsplash"
    if author:
        return f"Photo by {author} on Unsplash"
    return description


def parse_photo(item: dict[str, Any]) -> UnsplashPhoto | None:
    """把 API 返回的单条 photo 对象转成 `UnsplashPhoto`；缺图地址则返回 None。"""
    urls = item.get("urls") or {}
    image_url = (
        urls.get("regular")
        or urls.get("small")
        or urls.get("full")
        or urls.get("raw")
        or ""
    )
    if not image_url:
        return None

    links = item.get("links") or {}
    user = item.get("user") or {}
    return UnsplashPhoto(
        image_url=image_url,
        thumb_url=(urls.get("small") or urls.get("thumb") or urls.get("regular") or ""),
        page_url=links.get("html") or "",
        author=(user.get("name") or user.get("username") or "").strip(),
        description=(
            item.get("alt_description") or item.get("description") or ""
        ).strip(),
    )


class UnsplashClient:
    """线程内可复用的 Unsplash 搜索客户端。"""

    def __init__(
        self,
        access_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        http_client: RetryingHttpClient | None = None,
    ) -> None:
        self.access_key = (access_key or "").strip()
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._http = http_client or RetryingHttpClient(
            provider="unsplash", timeout_s=timeout_s, max_retries=max_retries
        )

    def require_key(self, ability_label: str) -> None:
        """缺 Key 时立刻抛可读错误，避免发一次必然 401 的请求。"""
        if not self.access_key:
            raise ProviderAuthError(
                f"未配置 Unsplash Access Key（设置页 → {ability_label}）",
                provider="unsplash",
            )

    def download(self, url: str, *, max_bytes: int | None = None) -> tuple[bytes, str]:
        """下载图片字节（用于颜色分析等本地处理，不对外展示）。"""
        return self._http.get_bytes(url, max_bytes=max_bytes)

    def search(self, query: str, count: int) -> list[UnsplashPhoto]:
        """按关键词搜图并截断到 `count`（必要时翻页）。"""
        query = (query or "").strip()
        if not query:
            return []

        want = max(1, count)
        photos: list[UnsplashPhoto] = []
        page = 1

        while len(photos) < want and page <= MAX_PAGES:
            per_page = min(MAX_PER_PAGE, want - len(photos))
            payload = self._search_page(query, per_page, page)
            batch = payload.get("results") or []

            for item in batch:
                parsed = parse_photo(item)
                if parsed is not None:
                    photos.append(parsed)

            total_pages = int(payload.get("total_pages") or 1)
            if len(batch) < per_page or page >= total_pages:
                break
            page += 1

        return photos[:want]

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _search_page(self, query: str, per_page: int, page: int) -> dict[str, Any]:
        params = urlencode(
            {
                "query": query,
                "per_page": per_page,
                "page": page,
                "content_filter": "low",
            }
        )
        return self._http.get_json(
            f"{self.base_url}/search/photos?{params}",
            headers={
                "Authorization": f"Client-ID {self.access_key}",
                "Accept-Version": "v1",
            },
        )

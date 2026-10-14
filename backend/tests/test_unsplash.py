"""Unsplash 服装图搜索适配器测试（离线，MockTransport）。

覆盖官方契约要点：Client-ID 鉴权、分页、结果映射与摄影师署名、
以及 401/429 的可读错误。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.abilities.clothing_search import UnsplashClothingSearchProvider
from app.abilities.clothing_search.unsplash import DEFAULT_QUERY
from app.abilities.http import (
    ProviderAuthError,
    ProviderRateLimitError,
    RetryingHttpClient,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler, **kwargs) -> UnsplashClothingSearchProvider:
    return UnsplashClothingSearchProvider(
        access_key="test-access-key",
        http_client=RetryingHttpClient(
            provider="unsplash",
            max_retries=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
        **kwargs,
    )


def _item(idx: str, *, author: str = "Jeff Sheldon", desc: str | None = "silk dress"):
    return {
        "id": f"photo-{idx}",
        "alt_description": desc,
        "description": None,
        "urls": {
            "raw": f"https://images.unsplash.com/photo-{idx}?ixid=1",
            "regular": f"https://images.unsplash.com/photo-{idx}?w=1080",
            "small": f"https://images.unsplash.com/photo-{idx}?w=400",
        },
        "links": {"html": f"https://unsplash.com/photos/photo-{idx}"},
        "user": {"name": author, "links": {"html": "https://unsplash.com/@ugmonk"}},
    }


def _page(items: list[dict], total_pages: int = 1) -> httpx.Response:
    return httpx.Response(
        200,
        json={"total": len(items), "total_pages": total_pages, "results": items},
    )


def test_sends_client_id_and_maps_results() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _page([_item("1"), _item("2")])

    results = _provider(handler).search(["pinterest", "taobao"], "silk dress", 2)

    assert len(results) == 2
    first = results[0]
    assert first.provider == "unsplash"
    assert first.site == "unsplash"
    assert first.external_url == "https://images.unsplash.com/photo-1?w=1080"
    assert first.page_url == "https://unsplash.com/photos/photo-1"
    assert first.source_query == "silk dress"
    # 官方要求标注摄影师与 Unsplash
    assert "Jeff Sheldon" in first.title
    assert "Unsplash" in first.title

    request = calls[0]
    assert request.headers["authorization"] == "Client-ID test-access-key"
    assert request.url.params["query"] == "silk dress"
    assert request.url.params["per_page"] == "2"
    assert request.url.params["page"] == "1"
    # sites 不参与请求（Unsplash 无站点过滤）
    assert "site" not in request.url.params


def test_pages_until_count_is_reached() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pages.append(page)
        per_page = int(request.url.params["per_page"])
        return _page([_item(f"{page}-{i}") for i in range(per_page)], total_pages=5)

    results = _provider(handler).search(["x"], "dress", 35)

    assert pages == ["1", "2"]  # 单页上限 30 → 需要翻页
    assert len(results) == 35


def test_stops_when_upstream_returns_less_than_requested() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _page([_item("1")], total_pages=9)

    results = _provider(handler).search(["x"], "dress", 20)

    assert len(results) == 1
    assert calls["n"] == 1  # 上游没货就不再翻页


def test_blank_query_falls_back_to_default() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["query"])
        return _page([_item("1")])

    _provider(handler).search(["x"], "   ", 1)
    assert seen == [DEFAULT_QUERY]


def test_items_without_urls_are_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        broken = _item("bad")
        broken["urls"] = {}
        return _page([broken, _item("ok")])

    results = _provider(handler).search(["x"], "dress", 2)
    assert [item.title for item in results] == [
        "silk dress · Photo by Jeff Sheldon on Unsplash"
    ]


def test_missing_access_key_fails_fast_without_request() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls["n"] += 1
        return _page([])

    provider = UnsplashClothingSearchProvider(
        access_key="",
        http_client=RetryingHttpClient(
            provider="unsplash",
            max_retries=0,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
    )
    with pytest.raises(ProviderAuthError) as info:
        provider.search(["x"], "dress", 1)

    assert "Access Key" in str(info.value)
    assert calls["n"] == 0


def test_invalid_key_surfaces_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errors": ["Invalid Access Token"]})

    with pytest.raises(ProviderAuthError):
        _provider(handler).search(["x"], "dress", 1)


def test_rate_limit_surfaces_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"errors": ["Rate limit exceeded"]})

    with pytest.raises(ProviderRateLimitError) as info:
        _provider(handler).search(["x"], "dress", 1)

    assert "限流" in str(info.value)

"""Unsplash 材质图检索适配器测试（离线，MockTransport）。"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.abilities.base import MaterialQuery
from app.abilities.http import ProviderAuthError, RetryingHttpClient
from app.abilities.material_search import UnsplashMaterialSearchProvider

Handler = Callable[[httpx.Request], httpx.Response]


def _provider(handler: Handler, **kwargs) -> UnsplashMaterialSearchProvider:
    return UnsplashMaterialSearchProvider(
        access_key="test-access-key",
        http_client=RetryingHttpClient(
            provider="unsplash",
            max_retries=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
        **kwargs,
    )


def _item(idx: str) -> dict:
    return {
        "id": f"photo-{idx}",
        "alt_description": "close up of fabric",
        "urls": {"regular": f"https://images.unsplash.com/photo-{idx}?w=1080"},
        "links": {"html": f"https://unsplash.com/photos/photo-{idx}"},
        "user": {"name": "Annie Spratt"},
    }


def _page(items: list[dict]) -> httpx.Response:
    return httpx.Response(
        200, json={"total": len(items), "total_pages": 1, "results": items}
    )


def test_queries_once_per_anchor_using_english_name() -> None:
    queries: list[str] = []
    sizes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["query"])
        sizes.append(request.url.params["per_page"])
        return _page([_item("1"), _item("2")])

    anchors = [
        MaterialQuery(material="桑蚕丝", material_en="Mulberry Silk", rank=0),
        MaterialQuery(material="棉", material_en="Cotton", rank=1),
    ]
    results = _provider(handler).search(anchors, per_tag=2)

    assert queries == [
        "Mulberry Silk fabric texture close up",
        "Cotton fabric texture close up",
    ]
    assert sizes == ["2", "2"]  # 每个检索锚只发一次请求
    assert [item.label for item in results] == ["桑蚕丝", "桑蚕丝", "棉", "棉"]
    assert [item.rank for item in results] == [0, 1, 2, 3]
    assert all(item.origin == "search" for item in results)
    assert all(
        item.external_url.startswith("https://images.unsplash.com/") for item in results
    )
    assert results[0].source_url == "https://unsplash.com/photos/photo-1"


def test_ascii_hints_are_appended_but_chinese_ones_are_dropped() -> None:
    """颜色 / 图案 / 光泽只拼 ASCII 的：中文对 Unsplash 是噪声（实测命中率低）。"""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["query"])
        return _page([_item("1")])

    _provider(handler).search(
        [
            MaterialQuery(
                material="醋酸",
                material_en="Acetate",
                color="navy blue",
                pattern="纯色",
                gloss="satin",
            )
        ],
        per_tag=1,
    )

    assert queries == ["navy blue satin Acetate fabric texture close up"]


def test_falls_back_to_taxonomy_keyword_without_english_name() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["query"])
        return _page([_item("1")])

    # 词表里 桑蚕丝 的 keywords[0] 是英文，可用于 Unsplash
    _provider(handler).search([MaterialQuery(material="桑蚕丝")], per_tag=1)

    assert queries == ["mulberry silk fabric texture"]
    assert not queries[0].startswith("桑蚕丝")


def test_similarity_is_a_descending_rank_proxy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _page([_item("1"), _item("2"), _item("3")])

    results = _provider(handler).search(
        [MaterialQuery(material="棉", material_en="Cotton")], per_tag=3
    )

    scores = [item.similarity for item in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < score <= 1.0 for score in scores)


def test_empty_queries_make_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("空检索锚不应发起请求")

    assert _provider(handler).search([]) == []


def test_missing_key_fails_fast_without_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("缺 Key 不应发起请求")

    provider = UnsplashMaterialSearchProvider(
        access_key="",
        http_client=RetryingHttpClient(
            provider="unsplash",
            max_retries=0,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
    )
    with pytest.raises(ProviderAuthError) as info:
        provider.search([MaterialQuery(material="棉", material_en="Cotton")])
    assert "查找材质图" in str(info.value)

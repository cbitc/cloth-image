"""Unsplash 材质图检索适配器测试（离线，MockTransport）。"""

from __future__ import annotations

import io
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.abilities.base import MaterialQuery
from app.abilities.http import ProviderAuthError, RetryingHttpClient
from app.abilities.material_search import UnsplashMaterialSearchProvider

Handler = Callable[[httpx.Request], httpx.Response]

#: 搜索端点的 path（图片下载走别的 path，测试里据此分流）
SEARCH_PATH = "/search/photos"


def _png(rgb: tuple[int, int, int] = (200, 40, 40), size: int = 16) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def _photo_id(request: httpx.Request) -> str:
    """从缩略图 URL（如 /photo-2?w=400）取 photo id，用于按图返回不同颜色。"""
    return request.url.path.rsplit("/", 1)[-1]


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
        "urls": {
            "regular": f"https://images.unsplash.com/photo-{idx}?w=1080",
            "small": f"https://images.unsplash.com/photo-{idx}?w=400",
        },
        "links": {"html": f"https://unsplash.com/photos/photo-{idx}"},
        "user": {"name": "Annie Spratt"},
    }


def _page(items: list[dict]) -> httpx.Response:
    return httpx.Response(
        200, json={"total": len(items), "total_pages": 1, "results": items}
    )


def test_queries_once_per_anchor_using_english_name() -> None:
    """没有颜色信息 → 每个检索锚只发一次「材质名」请求（不过采样、不下载缩略图）。"""
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


def test_chinese_pattern_and_gloss_are_translated_into_the_query() -> None:
    """回归：中文受控枚举曾经被 `isascii()` 丢掉，现在必须进入检索词。"""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(404)  # 缩略图：判不颜色，但不该影响检索词
        queries.append(request.url.params["query"])
        return _page([_item("1")])

    _provider(handler).search(
        [
            MaterialQuery(
                material="醋酸",
                material_en="Acetate",
                color="深灰蓝",
                color_hex="#1B2A4A",
                pattern="格纹",
                gloss="缎面",
            )
        ],
        per_tag=1,
    )

    # 具体变体在前（色词 + 图案词），材质名变体在后面兜底
    assert queries == [
        "navy blue plaid Acetate fabric texture close up",
        "Acetate fabric texture close up",
    ]


def test_solid_pattern_swaps_in_the_gloss_word() -> None:
    """纯色时图案词无区分度 → 改拼光泽词（此时光泽才是主要视觉差异）。"""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(404)
        queries.append(request.url.params["query"])
        return _page([_item("1")])

    _provider(handler).search(
        [
            MaterialQuery(
                material="棉",
                material_en="Cotton",
                color_hex="#1B2A4A",
                pattern="纯色",
                gloss="缎面",
            )
        ],
        per_tag=1,
    )

    assert queries[0] == "navy blue satin Cotton fabric texture close up"


def test_ascii_colour_name_is_used_when_hex_is_missing() -> None:
    """没有 hex 时，模型直接给的英文色名仍可用（不再因为中文规则而丢失）。"""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(404)
        queries.append(request.url.params["query"])
        return _page([_item("1")])

    _provider(handler).search(
        [
            MaterialQuery(
                material="醋酸",
                material_en="Acetate",
                color="navy blue",
                pattern="纯色",
                gloss="缎面",
            )
        ],
        per_tag=1,
    )

    assert queries[0] == "navy blue satin Acetate fabric texture close up"


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


# --------------------------------------------------------------------------- #
# 颜色重排
# --------------------------------------------------------------------------- #
def test_colour_rerank_promotes_the_best_matching_candidate() -> None:
    colours = {"photo-1": (245, 240, 220), "photo-2": (27, 42, 74)}  # 米白 / 藏青

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(200, content=_png(colours[_photo_id(request)]))
        return _page([_item("1"), _item("2")])

    results = _provider(handler).search(
        [MaterialQuery(material="棉", material_en="Cotton", color_hex="#1B2A4A")],
        per_tag=2,
    )

    assert [item.external_url for item in results] == [
        "https://images.unsplash.com/photo-2?w=1080",
        "https://images.unsplash.com/photo-1?w=1080",
    ]
    assert results[0].similarity > results[1].similarity
    assert [item.rank for item in results] == [0, 1]


def test_colour_rerank_oversamples_the_candidate_pool() -> None:
    sizes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(404)
        sizes.append(request.url.params["per_page"])
        return _page([_item("1")])

    _provider(handler, oversample=4).search(
        [MaterialQuery(material="棉", material_en="Cotton", color_hex="#1B2A4A")],
        per_tag=2,
    )

    assert sizes == ["8", "8"]  # 有颜色信息 → 每个变体都按 per_tag*oversample 多取候选


def test_rerank_max_caps_colour_inspections() -> None:
    inspected: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            inspected.append(request.url.path)
            return httpx.Response(200, content=_png((10, 10, 10)))
        return _page([_item(str(index)) for index in range(1, 9)])

    _provider(handler, oversample=6, rerank_max=3).search(
        [MaterialQuery(material="棉", material_en="Cotton", color_hex="#1B2A4A")],
        per_tag=2,
    )

    assert len(inspected) == 3


def test_unreachable_thumbnails_do_not_drop_results() -> None:
    """缩略图下载失败只意味着「没有颜色信息」，绝不能因此丢掉候选。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(500)
        return _page([_item("1"), _item("2")])

    results = _provider(handler).search(
        [MaterialQuery(material="棉", material_en="Cotton", color_hex="#1B2A4A")],
        per_tag=2,
    )

    assert len(results) == 2
    assert all(0.0 < item.similarity <= 1.0 for item in results)


def test_rerank_disabled_keeps_library_order() -> None:
    image_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            image_requests.append(request.url.path)
            return httpx.Response(404)
        return _page([_item("1"), _item("2")])

    results = _provider(handler, rerank_enabled=False).search(
        [MaterialQuery(material="棉", material_en="Cotton", color_hex="#1B2A4A")],
        per_tag=2,
    )

    assert image_requests == []  # 关闭重排 → 不做任何额外下载
    assert [item.external_url for item in results] == [
        "https://images.unsplash.com/photo-1?w=1080",
        "https://images.unsplash.com/photo-2?w=1080",
    ]
    assert results[0].similarity > results[1].similarity  # 名次代理兜底


def test_variant_results_are_deduplicated_by_image_url() -> None:
    """两个变体返回重叠候选时，同一张图只保留一次。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != SEARCH_PATH:
            return httpx.Response(404)
        return _page([_item("1"), _item("2")])

    results = _provider(handler).search(
        [MaterialQuery(material="棉", material_en="Cotton", pattern="格纹")],
        per_tag=3,
    )

    urls = [item.external_url for item in results]
    assert urls == [
        "https://images.unsplash.com/photo-1?w=1080",
        "https://images.unsplash.com/photo-2?w=1080",
    ]

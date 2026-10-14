"""OpenAI 兼容生图适配器测试（离线）。

重点覆盖实测踩到的坑：
  - 响应 `data` 是「被转义的 JSON 字符串」数组
  - `size` 必须用 `x` 分隔
  - 参考图数组（多参考图）与截断
  - 本机地址不能被当作参考图传出去
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.abilities.base import MaterialImageResult, ReferenceImage
from app.abilities.design_generate import OpenAICompatibleImageGenerator
from app.abilities.http import ProviderError, RetryingHttpClient

Handler = Callable[[httpx.Request], httpx.Response]

_IMAGE_URL = "https://dashscope-oss.example.com/generated/a.png"


def _png(color: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _generator(handler: Handler, **kwargs) -> OpenAICompatibleImageGenerator:
    return OpenAICompatibleImageGenerator(
        api_key="test-key",
        base_url="https://img.test/compatible-mode/v1",
        model="qwen-image-3.0",
        http_client=RetryingHttpClient(
            provider="test-img",
            max_retries=1,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
        **kwargs,
    )


def _ok_response(url: str = _IMAGE_URL, count: int = 1) -> httpx.Response:
    """复刻阿里 MaaS 的真实形态：data 是字符串数组，元素是被转义的 JSON。"""
    return httpx.Response(
        200,
        json={
            "created": 1,
            "data": [json.dumps({"url": url}) for _ in range(count)],
            "usage": {
                "output_width": 1024,
                "output_height": 1024,
                "input_image_count": 0,
                "output_image_count": count,
            },
        },
    )


def test_parses_escaped_json_string_data() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _ok_response()

    results = _generator(handler).generate([], "改成收腰版型", num_candidates=1)

    assert len(results) == 1
    assert results[0].external_url == _IMAGE_URL
    assert results[0].is_mock is False
    assert results[0].model == "qwen-image-3.0"

    body = calls[0]
    assert body["size"] == "1024x1024"  # 用 x，不是 *
    assert body["prompt_extend"] is False
    assert body["n"] == 1
    assert "image" not in body  # 无参考图 → 纯文生图
    assert "改成收腰版型" in body["prompt"]


def test_accepts_object_array_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"url": _IMAGE_URL}]})

    assert _generator(handler).generate([], "x")[0].external_url == _IMAGE_URL


def test_multiple_candidates_return_ranked_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    json.dumps({"url": f"https://oss.example.com/{i}.png"})
                    for i in range(3)
                ]
            },
        )

    results = _generator(handler).generate([], "x", num_candidates=3)
    assert [r.rank for r in results] == [0, 1, 2]


def test_references_are_sent_as_data_urls_and_truncated_to_max_refs() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _ok_response()

    materials = [
        MaterialImageResult(tag=f"材质{i}", image_bytes=_png()) for i in range(6)
    ]
    reference = ReferenceImage(image_bytes=_png())

    _generator(handler, max_refs=3).generate(
        materials, "x", reference, num_candidates=1
    )

    images = calls[0]["image"]
    assert isinstance(images, list)
    assert len(images) == 3  # 原服装图 + 2 张材质图
    assert all(url.startswith("data:image/jpeg;base64,") for url in images)


def test_single_reference_is_sent_as_string_not_list() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _ok_response()

    _generator(handler).generate(
        [MaterialImageResult(tag="棉", image_bytes=_png())], "x", num_candidates=1
    )
    assert isinstance(calls[0]["image"], str)


def test_localhost_reference_is_skipped() -> None:
    """本机 URL 外部服务访问不到，不能传出去。"""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _ok_response()

    _generator(handler).generate(
        [
            MaterialImageResult(
                tag="棉", external_url="http://localhost:8000/media/materials/a.png"
            )
        ],
        "x",
        num_candidates=1,
    )
    assert "image" not in calls[0]


def test_public_reference_url_is_passed_through() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _ok_response()

    _generator(handler).generate(
        [MaterialImageResult(tag="棉", external_url="https://cdn.example.com/m.jpg")],
        "x",
        num_candidates=1,
    )
    assert calls[0]["image"] == "https://cdn.example.com/m.jpg"


def test_invalid_size_format_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="1024x1024"):
        _generator(lambda request: _ok_response(), size="1024*1024")


def test_missing_url_in_response_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    with pytest.raises(ProviderError):
        _generator(handler).generate([], "x")


def test_usage_is_recorded() -> None:
    identifier = _generator(lambda request: _ok_response())
    identifier.generate([], "x", num_candidates=1)
    assert identifier.last_usage is not None
    assert identifier.last_usage["output_width"] == 1024

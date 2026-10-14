"""外部图片下载与镜像落盘测试（离线）。

镜像这一步很关键：生图返回的是 OSS 临时地址，不镜像就会静默失效。
"""

from __future__ import annotations

import io
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.abilities.http import ProviderError, RetryingHttpClient
from app.storage import get_storage
from app.tasks.fetch import fetch_image_bytes, mirror_image

Handler = Callable[[httpx.Request], httpx.Response]


def _png(size: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), (120, 180, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _client(handler: Handler) -> RetryingHttpClient:
    return RetryingHttpClient(
        provider="test-download",
        max_retries=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=lambda _seconds: None,
    )


def test_fetch_image_bytes_returns_content_and_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_png(), headers={"content-type": "image/png"}
        )

    data, content_type = fetch_image_bytes(
        "https://cdn.example.com/a.png", client=_client(handler)
    )

    assert content_type == "image/png"
    assert data.startswith(b"\x89PNG")


def test_non_image_content_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html/>", headers={"content-type": "text/html"}
        )

    with pytest.raises(ProviderError, match="不是图片"):
        fetch_image_bytes("https://cdn.example.com/a.html", client=_client(handler))


def test_oversized_image_is_rejected_via_content_length() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # content-length 超过上限时应在下载前就拒绝
        return httpx.Response(
            200,
            content=b"x" * 5000,
            headers={"content-type": "image/png", "content-length": "5000"},
        )

    with pytest.raises(ProviderError):
        fetch_image_bytes(
            "https://cdn.example.com/big.png", client=_client(handler), max_bytes=1000
        )


def test_mirror_image_lands_in_own_storage() -> None:
    """OSS 临时地址 → 下载 → 落盘 → 返回自有 URL，且能读回字节。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_png(), headers={"content-type": "image/png"}
        )

    persisted = mirror_image(
        "https://dashscope-oss.example.com/tmp/generated.png",
        "designs",
        client=_client(handler),
    )

    assert persisted.storage_key.startswith("designs/")
    assert "/media/designs/" in persisted.image_url
    assert get_storage().get_bytes(persisted.storage_key) is not None


def test_mirror_failure_raises() -> None:
    """镜像失败直接抛错（不做外链降级，避免图片静默 404）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="link expired")

    with pytest.raises(ProviderError):
        mirror_image(
            "https://oss.example.com/gone.png", "designs", client=_client(handler)
        )

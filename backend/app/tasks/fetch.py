"""下载外部图片并镜像到自有对象存储。

为什么必须镜像：生图 / 图库返回的通常是**临时签名 URL**（例如阿里云 OSS 加速域名），
一段时间后即失效。若只存外链，数据库里看着正常，实际图片会静默 404。

同时，外部服务**访问不到**本机的 `http://localhost:8000/media/...`，
所以送模型时要用 base64 data URL，而不是自家 URL（见 `abilities/image_ops.py`）。
"""

from __future__ import annotations

import logging

from app.abilities.http import ProviderError, RetryingHttpClient
from app.config import get_settings
from app.tasks.persist import PersistedImage, persist_bytes, persist_external

logger = logging.getLogger(__name__)

_download_client: RetryingHttpClient | None = None


def get_download_client() -> RetryingHttpClient:
    """下载专用客户端：超时更短、重试更少（下载失败重试性价比低）。"""
    global _download_client
    if _download_client is None:
        settings = get_settings()
        _download_client = RetryingHttpClient(
            provider="image-download",
            timeout_s=min(30.0, settings.provider_timeout_s),
            max_retries=1,
        )
    return _download_client


def fetch_image_bytes(
    url: str,
    *,
    client: RetryingHttpClient | None = None,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    """下载图片，返回 (内容, content-type)。非图片内容会抛 ProviderError。"""
    settings = get_settings()
    limit = max_bytes or settings.download_max_bytes
    http = client or get_download_client()

    data, content_type = http.get_bytes(url, max_bytes=limit)
    if not content_type.startswith("image/"):
        raise ProviderError(
            f"外部资源不是图片（content-type={content_type}）: {url[:120]}",
            provider="image-download",
        )
    return data, content_type


def mirror_image(
    url: str,
    prefix: str,
    *,
    client: RetryingHttpClient | None = None,
    fallback_external: bool = True,
) -> PersistedImage:
    """下载外部图片 → 落盘 → 返回自有 URL。

    镜像失败时：`fallback_external=True` 会降级为直接引用外链（记 WARNING），
    避免因为一张图下载失败就让整个任务失败。生产环境可设为 False 以强制暴露问题。
    """
    try:
        data, content_type = fetch_image_bytes(url, client=client)
        return persist_bytes(prefix, data, content_type)
    except Exception as exc:  # noqa: BLE001
        if not fallback_external:
            raise
        logger.warning(
            "镜像外部图片失败，降级为直接引用外链（该 URL 可能过期）: %s (%s)",
            url[:120],
            exc,
        )
        return persist_external(prefix, url)

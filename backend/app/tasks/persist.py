"""图片落盘工具：把 provider 产出的字节写入对象存储并生成缩略图。

key 用内容哈希，天然去重（相同图片不会重复存储）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.abilities.image_ops import make_thumbnail
from app.storage import get_storage


@dataclass(slots=True)
class PersistedImage:
    image_url: str
    thumbnail_url: str
    storage_key: str
    thumbnail_key: str
    #: 内容 sha256 前 32 位；识别结果缓存与去重都用它。外部图未知时为空串
    image_hash: str = ""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def persist_bytes(
    prefix: str, data: bytes, content_type: str = "image/png"
) -> PersistedImage:
    """写入原图 + 缩略图，返回 URL / key。"""
    storage = get_storage()
    digest = _digest(data)
    ext = "png" if "png" in content_type else "jpg"
    key = f"{prefix}/{digest}.{ext}"
    thumb_key = f"{prefix}/thumb/{digest}.jpg"

    if storage.get_bytes(key) is None:
        storage.put_bytes(key, data, content_type)
    if storage.get_bytes(thumb_key) is None:
        try:
            thumb = make_thumbnail(data)
            storage.put_bytes(thumb_key, thumb, "image/jpeg")
        except Exception:  # noqa: BLE001 - 缩略图失败则退化为原图
            thumb_key = key

    return PersistedImage(
        image_url=storage.url_for(key),
        thumbnail_url=storage.url_for(thumb_key),
        storage_key=key,
        thumbnail_key=thumb_key,
        image_hash=digest,
    )


def persist_external(prefix: str, external_url: str) -> PersistedImage:
    """外部已托管图片：MVP 直接引用，不做镜像（TODO: 生产环境镜像到自有存储）。"""
    return PersistedImage(
        image_url=external_url,
        thumbnail_url=external_url,
        storage_key="",
        thumbnail_key="",
    )


def resolve_image(
    prefix: str, data: bytes | None, external_url: str, content_type: str
) -> PersistedImage:
    if data:
        return persist_bytes(prefix, data, content_type)
    return persist_external(prefix, external_url)

"""本地图片存储：写入本地目录，并通过 /media 路由对外提供。

流水线产出的图片（检索图 / 生成图 / 缩略图）统一经此落盘，返回可公开访问的 URL。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.config import get_settings


class LocalStorage:
    def __init__(self, root: Path, url_prefix: str, base_url: str) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.url_prefix = url_prefix.rstrip("/")
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"非法 key: {key}")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return f"{self.base_url}{self.url_prefix}/{key}"

    def get_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.exists() else None

    def local_path(self, key: str) -> Path:
        return self._path(key)


@lru_cache
def get_storage() -> LocalStorage:
    s = get_settings()
    return LocalStorage(
        Path(s.local_storage_dir), s.media_url_prefix, s.public_base_url
    )


def reset_storage_cache() -> None:
    get_storage.cache_clear()

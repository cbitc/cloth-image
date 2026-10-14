"""对象存储抽象：local（本地目录 + /media 静态服务）或 s3（MinIO / S3 兼容）。

流水线产出的图片（占位图 / 检索缩略图 / 生成图）统一经此落盘，返回可公开访问的 URL。
"""

from __future__ import annotations

import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings


class Storage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """写入对象，返回公开可访问的 URL。"""
        ...

    def url_for(self, key: str) -> str: ...

    def get_bytes(self, key: str) -> bytes | None:
        """读回对象内容；不存在返回 None。"""
        ...

    def local_path(self, key: str) -> Path | None:
        """仅 local 后端有本地文件路径；s3 返回 None。"""
        ...


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

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


class S3Storage:
    def __init__(self) -> None:
        import boto3  # 延迟导入，local 模式无需安装依赖

        s = get_settings()
        self.bucket = s.s3_bucket
        self.public_endpoint = s.s3_public_endpoint_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001 - 不存在则创建
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except Exception:  # noqa: BLE001
                pass

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        ctype = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=ctype,
        )
        return self.url_for(key)

    def url_for(self, key: str) -> str:
        return f"{self.public_endpoint}/{self.bucket}/{key}"

    def get_bytes(self, key: str) -> bytes | None:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception:  # noqa: BLE001
            return None

    def local_path(self, key: str) -> Path | None:
        return None


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(
        Path(s.local_storage_dir), s.media_url_prefix, s.public_base_url
    )


def reset_storage_cache() -> None:
    get_storage.cache_clear()

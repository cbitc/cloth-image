"""本地存储模式下的媒体文件服务（STORAGE_BACKEND=local 时启用）。

使用对象存储（MinIO/S3）时不需要此路由，图片由 MinIO 直接对外提供。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import get_settings
from app.storage import get_storage

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
def get_media(key: str) -> FileResponse:
    settings = get_settings()
    if settings.storage_backend == "s3":
        raise HTTPException(status_code=404, detail="媒体文件由对象存储提供")

    try:
        path = get_storage().local_path(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)

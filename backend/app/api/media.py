"""本地图片服务：把落盘图片通过 /media/{key} 对外提供。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.storage import get_storage

router = APIRouter(tags=["media"])


@router.get("/media/{key:path}")
def get_media(key: str) -> FileResponse:
    try:
        path = get_storage().local_path(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)

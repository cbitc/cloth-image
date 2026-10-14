"""识别结果缓存的运维接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.tasks import cache

router = APIRouter(prefix="/api/cache", tags=["cache"])


@router.get("/identify/stats")
def identify_stats(db: Session = Depends(get_db)) -> dict:
    """查看识别缓存规模与累计省下的 token 数。"""
    return cache.stats(db)


@router.delete("/identify")
def clear_identify(
    model: str | None = Query(
        default=None, description="只清某个模型的缓存，留空清全部"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """清空识别缓存（换模型或发现识别质量异常时使用）。"""
    return {"removed": cache.clear(db, model), "model": model}

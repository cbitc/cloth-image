"""searchClothingImages 的 HTTP 入口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.abilities.base import ClothingImageResult
from app.abilities.registry import get_abilities
from app.db.models import ClothingImage
from app.db.session import get_db
from app.schemas import (
    ClothingImageOut,
    SearchClothingRequest,
    SearchClothingResponse,
)
from app.tasks.persist import resolve_image

router = APIRouter(prefix="/api/search", tags=["search"])

# 可选网站（Mock 模式下为示例站点；真实模式可改为按 adapter 能力动态返回）
AVAILABLE_SITES = [
    {"id": "mock-shop", "label": "示例商城（mock-shop）"},
    {"id": "mock-lookbook", "label": "示例 Lookbook（mock-lookbook）"},
    {"id": "pinterest", "label": "Pinterest（需真实 provider）"},
    {"id": "taobao", "label": "淘宝（需真实 provider）"},
]


@router.get("/sites")
def list_sites() -> dict:
    abilities = get_abilities()
    return {"mode": abilities.mode, "sites": AVAILABLE_SITES}


@router.post("/clothing", response_model=SearchClothingResponse)
def search_clothing(
    payload: SearchClothingRequest, db: Session = Depends(get_db)
) -> SearchClothingResponse:
    abilities = get_abilities()
    try:
        results: list[ClothingImageResult] = abilities.clothing_search.search(
            payload.sites, payload.query, payload.count
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    stored: list[ClothingImage] = []
    for result in results:
        persisted = resolve_image(
            "clothing", result.image_bytes, result.external_url, result.content_type
        )
        row = ClothingImage(
            image_url=persisted.image_url,
            thumbnail_url=persisted.thumbnail_url,
            storage_key=persisted.storage_key or None,
            page_url=result.page_url,
            title=result.title,
            site=result.site,
            source_query=result.source_query,
            provider=result.provider,
        )
        db.add(row)
        stored.append(row)
    db.commit()
    for row in stored:
        db.refresh(row)

    return SearchClothingResponse(
        images=[ClothingImageOut.model_validate(r) for r in stored]
    )

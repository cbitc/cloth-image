"""searchClothingImages 的 HTTP 入口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.abilities.base import ClothingImageResult
from app.abilities.http import ProviderError
from app.abilities.registry import AbilityNotConfigured, get_abilities
from app.db.models import ClothingImage
from app.db.session import get_db
from app.schemas import (
    ClothingImageOut,
    SearchClothingRequest,
    SearchClothingResponse,
)
from app.tasks.persist import resolve_image

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/sites")
def list_sites() -> dict:
    """可选网站列表：由当前 provider 自行暴露（Unsplash 不支持站点过滤）。"""
    abilities = get_abilities()
    provider = abilities.providers.get("clothing_search", "")
    sites = list(getattr(abilities.clothing_search, "sites", []) or [])
    return {"provider": provider, "sites": sites}


@router.post("/clothing", response_model=SearchClothingResponse)
def search_clothing(
    payload: SearchClothingRequest, db: Session = Depends(get_db)
) -> SearchClothingResponse:
    abilities = get_abilities()
    try:
        results: list[ClothingImageResult] = abilities.clothing_search.search(
            payload.sites, payload.query, payload.count
        )
    except AbilityNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProviderError as exc:
        # 鉴权失败 / 限流 / 上游错误 → 502，带上可读原因（而不是裸 500）
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    stored: list[ClothingImage] = []
    for result in results:
        persisted = resolve_image(
            "clothing", result.image_bytes, result.external_url, result.content_type
        )
        row = ClothingImage(
            image_url=persisted.image_url,
            thumbnail_url=persisted.thumbnail_url,
            storage_key=persisted.storage_key or None,
            image_hash=persisted.image_hash,
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

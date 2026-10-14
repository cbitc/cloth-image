"""材质词表接口（供前端下拉 / 校验）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import MaterialTagDef
from app.taxonomy import load_taxonomy

router = APIRouter(prefix="/api/material-taxonomy", tags=["taxonomy"])


@router.get("", response_model=list[MaterialTagDef])
def get_taxonomy() -> list[MaterialTagDef]:
    return [MaterialTagDef(**item) for item in load_taxonomy()]

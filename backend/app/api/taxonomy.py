"""材质词表接口（供前端下拉 / 校验）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas import CardOptionsOut, MaterialTagDef
from app.taxonomy import card_options, load_taxonomy

router = APIRouter(prefix="/api/material-taxonomy", tags=["taxonomy"])


@router.get("", response_model=list[MaterialTagDef])
def get_taxonomy() -> list[MaterialTagDef]:
    return [MaterialTagDef(**item) for item in load_taxonomy()]


@router.get("/card-options", response_model=CardOptionsOut)
def get_card_options() -> CardOptionsOut:
    """材质卡片的受控取值（图案 5 类 / 光泽 4 档 / 品类 / 面料名 …）。

    集中由后端 taxonomy 提供，避免前端硬编码枚举后与后端漂移。
    """
    return CardOptionsOut(**card_options())

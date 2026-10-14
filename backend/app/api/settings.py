"""能力配置的读取与修改（设置页的后端）。

⚠️ 安全提醒：本服务**目前没有任何鉴权**。任何能连到 API 的人都可以修改 provider
配置并**写入** API Key。因此：

- 密钥永不回传（只回传 `configured` 布尔），风险限于「写入」而非「读取」
- 仅限本机 / 内网使用；对外暴露前必须先加鉴权
- 可用 `SETTINGS_WRITE_ENABLED=false` 关闭写入能力（只读查看）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import settings_store
from app.abilities.registry import get_abilities, reset_abilities_cache
from app.config import apply_overrides, get_settings
from app.db.session import get_db
from app.settings_spec import SettingsValidationError, validate_patch
from app.settings_view import build_settings_payload

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    """部分更新。值为 null 表示删除该项覆盖（回退到环境变量）。"""

    values: dict[str, object] = Field(default_factory=dict)


def _snapshot(db: Session) -> dict:
    overrides = settings_store.load_overrides(db)
    return build_settings_payload(get_settings(), get_abilities(), overrides)


def _guard_writable() -> None:
    if not get_settings().settings_write_enabled:
        raise HTTPException(
            status_code=403,
            detail="配置写入已被禁用（SETTINGS_WRITE_ENABLED=false）",
        )


@router.get("")
def read_settings(db: Session = Depends(get_db)) -> dict:
    """当前生效的配置 + 每个能力的可用状态。密钥只返回是否已配置。"""
    return _snapshot(db)


@router.put("")
def update_settings(payload: SettingsPatch, db: Session = Depends(get_db)) -> dict:
    _guard_writable()

    try:
        cleaned = validate_patch(payload.values)
    except SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not cleaned:
        raise HTTPException(status_code=400, detail="没有需要更新的配置项")

    settings_store.save_patch(db, cleaned)
    # 覆盖项变化后必须让 settings 与 abilities 的缓存都失效
    apply_overrides(settings_store.load_overrides(db))
    reset_abilities_cache()

    return _snapshot(db)


@router.delete("")
def reset_settings(db: Session = Depends(get_db)) -> dict:
    """清空全部覆盖项，回退到环境变量 / .env / 代码默认值。"""
    _guard_writable()

    removed = settings_store.clear_all(db)
    apply_overrides({})
    reset_abilities_cache()

    snapshot = _snapshot(db)
    snapshot["removed"] = removed
    return snapshot

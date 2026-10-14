"""设置覆盖项的持久化（表 `app_setting`）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppSetting
from app.settings_spec import EDITABLE_FIELD_NAMES


def load_overrides(db: Session) -> dict[str, Any]:
    """读取全部覆盖项（只取当前 spec 内的字段）。"""
    rows = db.execute(select(AppSetting)).scalars().all()
    return {row.key: row.value for row in rows if row.key in EDITABLE_FIELD_NAMES}


def save_patch(db: Session, patch: dict[str, Any]) -> None:
    """部分更新：值为 None 表示删除该覆盖（回退到环境变量）。"""
    for key, value in patch.items():
        row = db.get(AppSetting, key)
        if value is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.commit()


def clear_all(db: Session) -> int:
    rows = db.execute(select(AppSetting)).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)

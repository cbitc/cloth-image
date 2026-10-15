"""材质卡片识别结果缓存。

同一张图 + 同一个模型 → 直接复用上次识别出的材质卡片，省掉一次 VLM 调用
（实测单次识别约 1500 tokens，重复建任务是常见操作）。

设计要点：
- key = (图片内容 sha256, 模型名)。模型名参与 key，换模型后旧缓存自然失效，
  不会拿 qwen3-vl-plus 的结果冒充别的模型。
- 只缓存卡片的**语义部分**（含各区域的裁剪框）；swatch 字节不缓存，
  命中后由编排器拿原图按框重裁（比存图便宜，也避免去重逻辑重复），
  故缓存对「同一张图」才有意义。
- 只有拿到图片字节、算得出哈希时才缓存（外链图未下载时无法缓存）。
- 缓存读写都失败不应影响主流程（识别本身能跑就行）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.abilities.base import MaterialCardResult
from app.abilities.material_identify.card_normalize import (
    from_payload as card_from_payload,
    to_payload as card_to_payload,
)
from app.db.models import IdentifyCache

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def lookup(
    db: Session, image_hash: str, model: str
) -> tuple[MaterialCardResult | None, int]:
    """查缓存。返回 (卡片, 上次消耗的 tokens)；未命中返回 (None, 0)。"""
    if not image_hash or not model:
        return None, 0

    row = db.execute(
        select(IdentifyCache).where(
            IdentifyCache.image_hash == image_hash, IdentifyCache.model == model
        )
    ).scalar_one_or_none()

    if row is None:
        return None, 0

    card = card_from_payload(row.payload)
    if not card.regions:
        # 缓存内容坏了，删掉让它重新识别
        db.delete(row)
        db.commit()
        return None, 0

    row.hits += 1
    row.last_used_at = _now()
    db.commit()
    return card, row.total_tokens


def store(
    db: Session,
    image_hash: str,
    model: str,
    card: MaterialCardResult,
    total_tokens: int = 0,
) -> None:
    """写缓存（同 key 覆盖）。"""
    if not image_hash or not model or not card.regions:
        return

    payload = card_to_payload(card)
    row = db.execute(
        select(IdentifyCache).where(
            IdentifyCache.image_hash == image_hash, IdentifyCache.model == model
        )
    ).scalar_one_or_none()

    if row is None:
        db.add(
            IdentifyCache(
                image_hash=image_hash,
                model=model,
                payload=payload,
                total_tokens=total_tokens,
            )
        )
    else:
        row.payload = payload
        row.total_tokens = total_tokens
        row.last_used_at = _now()
    db.commit()


def stats(db: Session) -> dict[str, Any]:
    rows = db.execute(select(IdentifyCache)).scalars().all()
    return {
        "entries": len(rows),
        "total_hits": sum(row.hits for row in rows),
        "saved_tokens": sum(row.total_tokens * row.hits for row in rows),
        "models": sorted({row.model for row in rows}),
    }


def clear(db: Session, model: str | None = None) -> int:
    stmt = select(IdentifyCache)
    if model:
        stmt = stmt.where(IdentifyCache.model == model)
    rows = db.execute(stmt).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return len(rows)

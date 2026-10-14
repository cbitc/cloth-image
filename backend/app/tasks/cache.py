"""材质识别结果缓存。

同一张图 + 同一个模型 → 直接复用上次结果，省掉一次 VLM 调用
（实测单次识别约 1500 tokens，重复建任务是常见操作）。

设计要点：
- key = (图片内容 sha256, 模型名)。模型名参与 key，换模型后旧缓存自然失效，
  不会拿 qwen3-vl-plus 的结果冒充别的模型。
- 只有拿到图片字节、算得出哈希时才缓存（外链图未下载时无法缓存）。
- 缓存读写都失败不应影响主流程（识别本身能跑就行）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.abilities.base import MaterialTagResult
from app.db.models import IdentifyCache

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_payload(tags: list[MaterialTagResult]) -> list[dict[str, Any]]:
    return [
        {
            "material": tag.material,
            "material_en": tag.material_en,
            "confidence": tag.confidence,
            "evidence": tag.evidence,
            "category": tag.category,
            "rank": tag.rank,
        }
        for tag in tags
    ]


def from_payload(payload: Any) -> list[MaterialTagResult]:
    if not isinstance(payload, list):
        return []
    tags: list[MaterialTagResult] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        tags.append(
            MaterialTagResult(
                material=str(item.get("material") or ""),
                material_en=str(item.get("material_en") or ""),
                confidence=float(item.get("confidence") or 0.0),
                evidence=str(item.get("evidence") or ""),
                category=str(item.get("category") or ""),
                rank=int(item.get("rank") if item.get("rank") is not None else index),
            )
        )
    return tags


def lookup(
    db: Session, image_hash: str, model: str
) -> tuple[list[MaterialTagResult], int]:
    """查缓存。返回 (tags, 上次消耗的 tokens)；未命中返回 ([], 0)。"""
    if not image_hash or not model:
        return [], 0

    row = db.execute(
        select(IdentifyCache).where(
            IdentifyCache.image_hash == image_hash, IdentifyCache.model == model
        )
    ).scalar_one_or_none()

    if row is None:
        return [], 0

    tags = from_payload(row.payload)
    if not tags:
        # 缓存内容坏了，删掉让它重新识别
        db.delete(row)
        db.commit()
        return [], 0

    row.hits += 1
    row.last_used_at = _now()
    db.commit()
    return tags, row.total_tokens


def store(
    db: Session,
    image_hash: str,
    model: str,
    tags: list[MaterialTagResult],
    total_tokens: int = 0,
) -> None:
    """写缓存（同 key 覆盖）。"""
    if not image_hash or not model or not tags:
        return

    payload = to_payload(tags)
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

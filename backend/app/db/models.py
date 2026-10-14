"""SQLAlchemy ORM 模型。

表结构：
  clothing_image  搜索得到的服装图（可作为任务的输入）
  task            一个任务 = 一张被选中的服装图走一遍流水线
  material_tag    材质 tag（AI 识别 + 用户确认后）
  material_image  材质图（按 tag 检索得到）
  design_image    生成的设计图
  task_event      任务进度事件（用于 SSE 推送与审计）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.enums import TagSource, TaskStatus


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ClothingImage(Base):
    """搜索服装图的检索结果。"""

    __tablename__ = "clothing_image"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    image_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    site: Mapped[str] = mapped_column(String(64), default="")
    source_query: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    __tablename__ = "task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    clothing_image_id: Mapped[str] = mapped_column(
        ForeignKey("clothing_image.id"), index=True
    )

    status: Mapped[str] = mapped_column(
        String(32), default=TaskStatus.PENDING, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    design_idea: Mapped[str] = mapped_column(Text, default="")
    auto_generate: Mapped[bool] = mapped_column(Boolean, default=False)
    require_material_selection: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    clothing_image: Mapped[ClothingImage] = relationship(lazy="joined")
    material_tags: Mapped[list["MaterialTag"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="MaterialTag.rank"
    )
    material_images: Mapped[list["MaterialImage"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    design_images: Mapped[list["DesignImage"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    events: Mapped[list["TaskEvent"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class MaterialTag(Base):
    __tablename__ = "material_tag"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)

    material: Mapped[str] = mapped_column(String(64))  # 中文名
    material_en: Mapped[str] = mapped_column(String(64), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(8), default=TagSource.AI)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="material_tags")


class MaterialImage(Base):
    __tablename__ = "material_image"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)

    tag: Mapped[str] = mapped_column(String(64), index=True)
    image_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="material_images")


class DesignImage(Base):
    __tablename__ = "design_image"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)

    image_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(64), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="design_images")


class TaskEvent(Base):
    __tablename__ = "task_event"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)

    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    task: Mapped[Task] = relationship(back_populates="events")

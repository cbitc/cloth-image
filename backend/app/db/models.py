"""SQLAlchemy ORM 模型。

表结构：
  clothing_image  搜索得到的服装图（可作为任务的输入）
  task            一个任务 = 一张被选中的服装图走一遍流水线
  material_card   材质卡片（识别结果，用户可编辑；一张任务一张卡片）
  material_image  面料参考图（按卡片检索得到 + 用户上传）
  design_image    生成的设计图
  task_event      任务进度事件（用于 SSE 推送与审计）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.enums import MaterialImageOrigin, MaterialSource, TaskStatus


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
    #: 图片内容的 sha256（前 32 位）—— 用于识别结果缓存与去重，外链图可能为空
    image_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    page_url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    site: Mapped[str] = mapped_column(String(64), default="")
    source_query: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="")
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
    #: 生成设计图时是否把原服装图作为参考图（True = 图生图保留版型；
    #: False = 只送材质图，退化为「材质图 + 文字描述版型」）
    use_reference: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    clothing_image: Mapped[ClothingImage] = relationship(lazy="joined")
    #: 材质卡片（1:1）。识别完成时创建；用户编辑只改卡片，不新建行
    material_card: Mapped["MaterialCard | None"] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
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


class MaterialCard(Base):
    """材质卡片：连接「识别」与「生成」的最小充分中间层（MVP 计划 §3.1）。

    卡片主体存 `payload` JSON —— 嵌套结构（区域 / 颜色 / 图案 / 光泽 / B、C 层 /
    逐字段置信度）随 Schema 演进时不必改表；只有需要查询与直接展示的少量字段单独成列。
    `swatch`（干净面料小样）是真实图片，必须落盘后存 key / URL。
    """

    __tablename__ = "material_card"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), unique=True, index=True)

    #: ai = 模型识别结果；user = 用户改过的卡片
    source: Mapped[str] = mapped_column(String(8), default=MaterialSource.AI)
    #: 品类（女装上衣 / 连衣裙），单独成列便于列表展示
    category: Mapped[str] = mapped_column(String(32), default="")
    #: 整张卡片（与 `card_normalize.to_payload` 对称）
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    #: 用户自由文本补充，编译进生图提示词
    note: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    #: 材质小样（干净面料 patch）：生成阶段的保真锚点
    swatch_url: Mapped[str] = mapped_column(Text, default="")
    swatch_thumbnail_url: Mapped[str] = mapped_column(Text, default="")
    swatch_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 归一化裁剪框 [left, top, right, bottom]（实际使用的那一个）
    swatch_crop_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #: 纹理指纹（embedding）引用；MVP 期留空
    texture_embedding_ref: Mapped[str] = mapped_column(String(128), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    task: Mapped[Task] = relationship(back_populates="material_card")


class MaterialImage(Base):
    """面料参考图：按卡片检索得到的，以及用户在任务详情页上传的。"""

    __tablename__ = "material_image"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("task.id"), index=True)

    #: 展示 / 提示词用标签：检索结果 = 材质名，上传 = 「上传的面料图」
    label: Mapped[str] = mapped_column(String(64), index=True)
    image_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    similarity: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    #: search = 按卡片检索；upload = 用户上传（重跑检索时不会被清掉）
    origin: Mapped[str] = mapped_column(
        String(16), default=MaterialImageOrigin.SEARCH, index=True
    )

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
    rank: Mapped[int] = mapped_column(Integer, default=0)
    #: 该候选是否**真的**把原服装图送进了模型（由 provider 依据实际参考图回报，
    #: 不是任务开关的复制：外链无字节、超参考图上限时会被丢弃）
    used_reference: Mapped[bool] = mapped_column(Boolean, default=False)

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


class IdentifyCache(Base):
    """材质识别结果缓存。

    同一张图（image_hash）+ 同一个模型 → 直接复用上次的识别结果，
    省掉一次 VLM 调用（实测单次约 1500 tokens）。
    模型名参与 key，因此换模型后缓存自动失效，不会串味。
    """

    __tablename__ = "identify_cache"
    __table_args__ = (
        UniqueConstraint("image_hash", "model", name="uq_identify_cache_hash_model"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    image_hash: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)

    #: 序列化后的材质卡片（与 card_normalize.to_payload 对称）
    payload: Mapped[list] = mapped_column(JSON, default=list)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    hits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )


class AppSetting(Base):
    """运行时配置覆盖项（在设置页由用户自行修改）。

    优先级：数据库覆盖 > 环境变量 / .env > 代码默认值。
    只存被用户改动过的键；删掉记录即回退到环境变量。
    """

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

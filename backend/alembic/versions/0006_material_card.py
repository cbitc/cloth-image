"""材质卡片：新建 material_card、删除 material_tag、material_image 改 label/origin

Revision ID: 0006_material_card
Revises: 0005_use_reference
Create Date: 2026-10-15

背景：识别输出由「材质 tag 列表」改为 MVP 计划的「材质卡片」（逐区域视觉属性 +
B/C 层占位 + 逐字段置信度 + 材质小样 swatch）。两者字段无法一一映射
（多 tag ↔ 单卡片），故直接下线 material_tag 而非做数据迁移。

注意：`material_image.tag` 重命名为 `label`，并新增 `origin`（search / upload）。
SQLite 下用 batch 模式重命名列（底层是 ALTER TABLE RENAME COLUMN）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_material_card"
down_revision = "0005_use_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "material_card",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="ai"),
        sa.Column("category", sa.String(32), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("overall_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("swatch_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("swatch_thumbnail_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("swatch_storage_key", sa.Text(), nullable=True),
        sa.Column("swatch_crop_box", sa.JSON(), nullable=True),
        sa.Column(
            "texture_embedding_ref", sa.String(128), nullable=False, server_default=""
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_material_card_task_id", "material_card", ["task_id"], unique=True
    )

    op.drop_table("material_tag")

    with op.batch_alter_table("material_image") as batch_op:
        batch_op.alter_column(
            "tag",
            new_column_name="label",
            existing_type=sa.String(64),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column("origin", sa.String(16), nullable=False, server_default="search")
        )
        batch_op.create_index("ix_material_image_origin", ["origin"])

    # 旧缓存 payload 是 tag 列表，与卡片结构不兼容 → 清空，
    # 否则 from_payload 会解析出一张空卡片（比不做缓存更糟）。
    op.execute("DELETE FROM identify_cache")


def downgrade() -> None:
    op.execute("DELETE FROM identify_cache")

    with op.batch_alter_table("material_image") as batch_op:
        batch_op.drop_index("ix_material_image_origin")
        batch_op.drop_column("origin")
        batch_op.alter_column(
            "label",
            new_column_name="tag",
            existing_type=sa.String(64),
            existing_nullable=False,
        )

    op.create_table(
        "material_tag",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), sa.ForeignKey("task.id"), nullable=False),
        sa.Column("material", sa.String(64), nullable=False),
        sa.Column("material_en", sa.String(64), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(32), nullable=False, server_default=""),
        sa.Column("source", sa.String(8), nullable=False, server_default="ai"),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_material_tag_task_id", "material_tag", ["task_id"])

    op.drop_index("ix_material_card_task_id", table_name="material_card")
    op.drop_table("material_card")

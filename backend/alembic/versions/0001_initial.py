"""初始表结构

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clothing_image",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("site", sa.String(length=64), nullable=False),
        sa.Column("source_query", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "task",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "clothing_image_id",
            sa.String(length=32),
            sa.ForeignKey("clothing_image.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("design_idea", sa.Text(), nullable=False),
        sa.Column("auto_generate", sa.Boolean(), nullable=False),
        sa.Column("require_material_selection", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_clothing_image_id", "task", ["clothing_image_id"])
    op.create_index("ix_task_status", "task", ["status"])

    op.create_table(
        "material_tag",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False
        ),
        sa.Column("material", sa.String(length=64), nullable=False),
        sa.Column("material_en", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
    )
    op.create_index("ix_material_tag_task_id", "material_tag", ["task_id"])

    op.create_table(
        "material_image",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False
        ),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
    )
    op.create_index("ix_material_image_task_id", "material_image", ["task_id"])
    op.create_index("ix_material_image_tag", "material_image", ["tag"])

    op.create_table(
        "design_image",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False
        ),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("is_mock", sa.Boolean(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
    )
    op.create_index("ix_design_image_task_id", "design_image", ["task_id"])

    op.create_table(
        "task_event",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "task_id", sa.String(length=32), sa.ForeignKey("task.id"), nullable=False
        ),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_event_task_id", "task_event", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_event")
    op.drop_table("design_image")
    op.drop_table("material_image")
    op.drop_table("material_tag")
    op.drop_table("task")
    op.drop_table("clothing_image")

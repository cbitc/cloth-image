"""识别结果缓存 + clothing_image.image_hash

Revision ID: 0002_identify_cache
Revises: 0001_initial
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_identify_cache"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 已有行用 server_default 兜底（SQLite 加 NOT NULL 列必须给默认值）
    op.add_column(
        "clothing_image",
        sa.Column(
            "image_hash", sa.String(length=64), nullable=False, server_default=""
        ),
    )
    op.create_index("ix_clothing_image_image_hash", "clothing_image", ["image_hash"])

    op.create_table(
        "identify_cache",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("image_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("image_hash", "model", name="uq_identify_cache_hash_model"),
    )
    op.create_index("ix_identify_cache_image_hash", "identify_cache", ["image_hash"])
    op.create_index("ix_identify_cache_model", "identify_cache", ["model"])


def downgrade() -> None:
    op.drop_table("identify_cache")
    op.drop_index("ix_clothing_image_image_hash", table_name="clothing_image")
    op.drop_column("clothing_image", "image_hash")

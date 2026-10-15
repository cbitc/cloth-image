"""task.use_reference（生成时是否参考原服装图）+ design_image.used_reference（实际是否参考）

Revision ID: 0005_use_reference
Revises: 0004_drop_is_mock
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_use_reference"
down_revision = "0004_drop_is_mock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 已有任务沿用旧行为（参考原图）；已有设计图无从追溯，一律按「未参考」处理
    op.add_column(
        "task",
        sa.Column(
            "use_reference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "design_image",
        sa.Column(
            "used_reference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    # SQLite 无法直接 DROP COLUMN，需 batch 模式重建表
    with op.batch_alter_table("design_image") as batch_op:
        batch_op.drop_column("used_reference")
    with op.batch_alter_table("task") as batch_op:
        batch_op.drop_column("use_reference")

"""删除 design_image.is_mock（不再区分 mock / 真实生图）

Revision ID: 0004_drop_is_mock
Revises: 0003_app_settings
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_drop_is_mock"
down_revision = "0003_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch 模式：SQLite 无法直接 DROP COLUMN，需重建表
    with op.batch_alter_table("design_image") as batch_op:
        batch_op.drop_column("is_mock")


def downgrade() -> None:
    with op.batch_alter_table("design_image") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_mock", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )

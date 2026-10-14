"""运行时配置覆盖表

Revision ID: 0003_app_settings
Revises: 0002_identify_cache
Create Date: 2026-10-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_app_settings"
down_revision = "0002_identify_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_setting")

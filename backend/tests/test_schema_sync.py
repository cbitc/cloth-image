"""SQLite 开发库 schema 自愈测试。

复刻现实场景：库是旧版本建的，表在但缺列 —— `create_all` 不会补列，
导致接口 500（表现为浏览器 "Failed to fetch"）。`sync_sqlite_schema` 负责补齐。
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from app.db.schema import sync_sqlite_schema


class _Base(DeclarativeBase):
    pass


class Widget(_Base):
    __tablename__ = "widget"

    id = sa.Column(sa.String(32), primary_key=True)
    # NOT NULL 且带 Python 默认值 → 补列时需生成 DEFAULT，否则 SQLite 会拒绝
    name = sa.Column(sa.String(64), default="x", nullable=False, index=True)
    note = sa.Column(sa.String(8))


def _engine(tmp_path) -> Engine:
    return sa.create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")


def test_adds_missing_columns_and_indexes(tmp_path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE widget (id VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO widget (id) VALUES ('a')"))

    applied = sync_sqlite_schema(engine, _Base.metadata)

    inspector = inspect(engine)
    assert {"name", "note"} <= {col["name"] for col in inspector.get_columns("widget")}
    assert "widget.name" in applied
    assert "widget.note" in applied
    assert any(item.startswith("index ") for item in applied)

    # 存量行用默认值补齐，不会因 NOT NULL 失败
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, name, note FROM widget")).first()
    assert row == ("a", "x", None)


def test_is_idempotent(tmp_path) -> None:
    engine = _engine(tmp_path)
    sync_sqlite_schema(engine, _Base.metadata)

    assert sync_sqlite_schema(engine, _Base.metadata) == []


def test_skips_non_sqlite_backends() -> None:
    class _FakeEngine:
        dialect = type("D", (), {"name": "postgresql"})()

    assert sync_sqlite_schema(_FakeEngine(), _Base.metadata) == []

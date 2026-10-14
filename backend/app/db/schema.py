"""SQLite 开发库的 schema 自愈（幂等）。

背景：MVP 启动用 `Base.metadata.create_all`，它只会**新建缺失的表**，
不会给**已存在的表**补列 / 补索引。于是旧库升级代码后会报
`no such column: clothing_image.image_hash`，接口直接 500。

这里做一次幂等补齐，免得每次改模型都要手动删库：

    sync_sqlite_schema(engine, Base.metadata)

- 只处理 SQLite；其它后端请走 alembic 迁移（compose 里已 `alembic upgrade head`）。
- `ALTER TABLE ADD COLUMN` 在 SQLite 上不能加「NOT NULL 且无默认值」的列：
  若模型带 Python 默认值就补上 `DEFAULT`，没有则退化为可空并打警告。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn, CreateIndex
from sqlalchemy.sql.schema import MetaData

logger = logging.getLogger(__name__)


def _column_ddl(column, dialect) -> tuple[str, bool]:
    """返回 (DDL 片段, 是否可安全添加)。"""
    ddl = str(CreateColumn(column).compile(dialect=dialect))
    if column.nullable or column.server_default is not None:
        return ddl, True

    default = getattr(getattr(column, "default", None), "arg", None)
    if isinstance(default, bool):
        return f"{ddl} DEFAULT {1 if default else 0}", True
    if isinstance(default, (int, float)):
        return f"{ddl} DEFAULT {default}", True
    if isinstance(default, str):
        escaped = default.replace("'", "''")
        return f"{ddl} DEFAULT '{escaped}'", True

    # 没有任何默认值：SQLite 无法加 NOT NULL 列，退化为可空
    return ddl.replace(" NOT NULL", ""), False


def sync_sqlite_schema(engine: Engine, metadata: MetaData) -> list[str]:
    """为已存在的 SQLite 表补齐缺失的列与索引，返回本次改动列表。"""
    if engine.dialect.name != "sqlite":
        return []

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all 已建（含索引）

            have_columns = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have_columns:
                    continue
                ddl, safe = _column_ddl(column, engine.dialect)
                quoted = engine.dialect.identifier_preparer.quote(table.name)
                conn.execute(text(f"ALTER TABLE {quoted} ADD COLUMN {ddl}"))
                applied.append(f"{table.name}.{column.name}")
                if not safe:
                    logger.warning(
                        "已为 %s.%s 补列，但模型要求 NOT NULL 且无默认值 → 暂以可空加入，"
                        "请检查存量数据或改用 alembic 迁移",
                        table.name,
                        column.name,
                    )

        # create_all 不会给已存在的表补索引，这里一并补上
        for table in metadata.sorted_tables:
            if table.name not in existing_tables or not table.indexes:
                continue
            have_indexes = {
                index["name"] for index in inspector.get_indexes(table.name)
            }
            for index in table.indexes:
                if index.name in have_indexes:
                    continue
                conn.execute(CreateIndex(index))
                applied.append(f"index {index.name}")

    return applied

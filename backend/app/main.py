"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__, settings_store
from app.ability_config import get_ability_settings
from app.abilities.registry import config_warnings, get_abilities, reset_abilities_cache
from app.api import (
    cache,
    events,
    media,
    search,
    settings as settings_api,
    tasks,
    taxonomy,
)
from app.config import apply_overrides, get_settings
from app.db import models  # noqa: F401  确保模型注册到 Base.metadata
from app.db.session import Base, SessionLocal, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # MVP：启动时确保表结构存在（生产环境请以 alembic 迁移为准）
    Base.metadata.create_all(bind=engine)

    # 先加载设置页写入的覆盖项，再构建能力实现（顺序不能反）
    with SessionLocal() as db:
        overrides = settings_store.load_overrides(db)
    apply_overrides(overrides)
    reset_abilities_cache()
    if overrides:
        logger.info(
            "已加载 %d 项用户配置覆盖：%s", len(overrides), "、".join(sorted(overrides))
        )

    abilities = get_abilities()
    logger.info("能力提供方：%s（mode=%s）", abilities.summary(), abilities.mode)
    if abilities.real_providers:
        logger.info("已启用真实能力：%s", "、".join(abilities.real_providers))
    for warning in config_warnings(abilities, get_ability_settings()):
        logger.warning("配置提醒：%s", warning)
    yield


app = FastAPI(
    title="AI 服装辅助设计 API",
    version=__version__,
    description="搜图 → 建任务 → 识别材质 → 检索材质图 → 图生图",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(taxonomy.router)
app.include_router(cache.router)
app.include_router(settings_api.router)
if settings.storage_backend == "local":
    app.include_router(media.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    effective = get_settings()
    abilities = get_abilities()
    return {
        "status": "ok",
        "version": __version__,
        "abilities": abilities.providers,
        "abilities_mode": abilities.mode,
        "storage_backend": effective.storage_backend,
        "task_execution": effective.task_execution,
    }

"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.abilities.registry import config_warnings, get_abilities
from app.api import events, media, search, tasks, taxonomy
from app.config import get_settings
from app.db import models  # noqa: F401  确保模型注册到 Base.metadata
from app.db.session import Base, engine

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

    abilities = get_abilities()
    logger.info("能力提供方：%s（mode=%s）", abilities.summary(), abilities.mode)
    if abilities.real_providers:
        logger.info("已启用真实能力：%s", "、".join(abilities.real_providers))
    for warning in config_warnings(settings, abilities):
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
if settings.storage_backend == "local":
    app.include_router(media.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    abilities = get_abilities()
    return {
        "status": "ok",
        "version": __version__,
        "provider_mode": settings.provider_mode,
        "abilities": abilities.providers,
        "abilities_mode": abilities.mode,
        "storage_backend": settings.storage_backend,
        "task_execution": settings.task_execution,
    }

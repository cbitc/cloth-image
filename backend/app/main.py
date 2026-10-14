"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    logger.info("能力提供方：%s", abilities.summary())
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


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理，并**手动补 CORS 头**。

    `ServerErrorMiddleware` 产生的 500 不经过 `CORSMiddleware`，浏览器因缺少
    `Access-Control-Allow-Origin` 会把错误报成 "Failed to fetch"（而非 500），
    极难排查。这里显式回一个带 CORS 头的 JSON 错误。
    """
    logger.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误：{type(exc).__name__}: {exc}"},
        headers={"Access-Control-Allow-Origin": "*"},
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
        "storage_backend": effective.storage_backend,
        "task_execution": effective.task_execution,
    }

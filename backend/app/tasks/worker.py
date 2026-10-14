"""Celery worker：把编排器的单阶段函数包装为 Celery 任务。

启动：celery -A app.tasks.worker.celery_app worker --loglevel=info --pool=solo
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings
from app.tasks import orchestrator

settings = get_settings()

celery_app = Celery(
    "cloth_image",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


@celery_app.task(name="cloth.identify")
def identify_task(task_id: str) -> str:
    orchestrator.run_identify(task_id)
    return task_id


@celery_app.task(name="cloth.material_search")
def material_search_task(task_id: str) -> str:
    orchestrator.run_material_search(task_id)
    return task_id


@celery_app.task(name="cloth.generate")
def generate_task(
    task_id: str, design_idea: str | None = None, num_candidates: int | None = None
) -> str:
    orchestrator.run_generate(task_id, design_idea, num_candidates)
    return task_id

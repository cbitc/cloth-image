"""SSE 进度推送：任务详情流 & 看板列表流。

前端用 EventSource 订阅，任务状态 / 图片就绪时自动刷新。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select

from app.db.models import Task, TaskEvent
from app.db.session import SessionLocal
from app.enums import TERMINAL_STATUSES, TaskStatus
from app.schemas import TaskDetail, TaskEventOut, TaskSummary
from app.tasks.serialize import build_detail, build_summary

router = APIRouter(prefix="/api", tags=["events"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data: object) -> str:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
    )


@router.get("/tasks/{task_id}/events")
async def stream_task_events(task_id: str, request: Request) -> StreamingResponse:
    async def generator():
        last_event_at: datetime | None = None
        last_marker: tuple | None = None
        while True:
            if await request.is_disconnected():
                break

            with SessionLocal() as db:
                task = db.get(Task, task_id)
                if task is None:
                    yield _sse("error", {"message": "任务不存在"})
                    break

                stmt = (
                    select(TaskEvent)
                    .where(TaskEvent.task_id == task_id)
                    .order_by(TaskEvent.created_at)
                )
                if last_event_at is not None:
                    stmt = stmt.where(TaskEvent.created_at > last_event_at)
                events = db.execute(stmt).scalars().all()

                card = task.material_card
                marker = (
                    task.status,
                    task.updated_at,
                    len(task.material_images),
                    len(task.design_images),
                    card.updated_at if card is not None else None,
                    card.source if card is not None else "",
                )

                payload: TaskDetail | None = None
                if marker != last_marker:
                    payload = build_detail(task)
                    last_marker = marker

                terminal = TaskStatus(task.status) in TERMINAL_STATUSES
                new_events = [
                    TaskEventOut.model_validate(e).model_dump(mode="json")
                    for e in events
                ]
                if events:
                    last_event_at = events[-1].created_at

            for item in new_events:
                yield _sse("event", item)
            if payload is not None:
                yield _sse("snapshot", payload.model_dump(mode="json"))

            if terminal and not new_events and payload is None:
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/events/stream")
async def stream_board(request: Request, limit: int = 100) -> StreamingResponse:
    async def generator():
        last_marker: list | None = None
        while True:
            if await request.is_disconnected():
                break

            with SessionLocal() as db:
                tasks = (
                    db.execute(
                        select(Task).order_by(desc(Task.created_at)).limit(limit)
                    )
                    .scalars()
                    .all()
                )
                marker = [(t.id, t.status, t.updated_at) for t in tasks]
                payload = None
                if marker != last_marker:
                    payload = [build_summary(t).model_dump(mode="json") for t in tasks]
                    last_marker = marker

            if payload is not None:
                yield _sse("tasks", payload)
            await asyncio.sleep(1.2)

    return StreamingResponse(
        generator(), media_type="text/event-stream", headers=SSE_HEADERS
    )

"""任务相关接口：创建 / 查询 / 人工检查点 / 生成。

流水线：
  POST   /api/tasks                       勾选 N 张图 → 创建 N 个任务（并发识别）
  GET    /api/tasks                       任务列表（看板）
  GET    /api/tasks/{id}                  任务详情
  POST   /api/tasks/{id}/confirm-materials  ★检查点1：确认 / 修改材质 tag → 触发材质检索
  POST   /api/tasks/{id}/select-materials   ★检查点2：挑选材质图
  POST   /api/tasks/{id}/generate           ★检查点3：填设计想法 → 生成设计图
  POST   /api/tasks/{id}/retry            失败重试
  DELETE /api/tasks/{id}
  POST   /api/tasks/bulk-delete          批量删除（按 id 列表）
  GET    /api/tasks/{id}/events           SSE 进度流
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import MaterialTag, Task
from app.db.session import get_db
from app.enums import TagSource, TaskStatus
from app.schemas import (
    BulkDeleteTasksRequest,
    BulkDeleteTasksResponse,
    ConfirmMaterialsRequest,
    CreateTasksRequest,
    CreateTasksResponse,
    GenerateRequest,
    SelectMaterialsRequest,
    TaskDetail,
    TaskSummary,
)
from app.taxonomy import get_definition
from app.tasks import orchestrator
from app.tasks.dispatcher import get_dispatcher
from app.tasks.serialize import build_detail, build_summary
from app.tasks.state_machine import can_transition

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_SELECT_STATES = {
    TaskStatus.AWAIT_MATERIAL_SELECT,
    TaskStatus.AWAIT_DESIGN_IDEA,
    TaskStatus.DONE,
}


def _get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    return task


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _advance(db: Session, task: Task, target: TaskStatus) -> None:
    """把任务推进到 `target` 并提交，**必须在派发后台任务之前**调用。

    `inline` 模式下派发是异步的（响应不阻塞）。若等 orchestrator 去改状态，
    响应会带着**旧状态**返回：前端以为还停在 DONE，「再生成一版」按钮仍可点，
    再点一次就被状态守卫判 409。这里先把状态落库，保证响应内容就是真实状态。
    """
    task.status = str(target)
    task.updated_at = _now()
    db.commit()


@router.post("", response_model=CreateTasksResponse, status_code=201)
def create_tasks(
    payload: CreateTasksRequest,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> CreateTasksResponse:
    tasks = orchestrator.create_tasks(
        db,
        payload.clothing_image_ids,
        design_idea=payload.design_idea.strip(),
        auto_generate=payload.auto_generate,
        require_material_selection=payload.require_material_selection,
    )
    if not tasks:
        raise HTTPException(status_code=400, detail="未找到有效的服装图片")

    summaries = [build_summary(t) for t in tasks]  # 先构造响应，再派发
    for task in tasks:
        dispatcher.dispatch_identify(task.id)
    return CreateTasksResponse(tasks=summaries)


@router.get("", response_model=list[TaskSummary])
def list_tasks(
    status: str | None = Query(default=None, description="按状态过滤"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[TaskSummary]:
    stmt = select(Task).order_by(desc(Task.created_at)).limit(limit)
    if status:
        stmt = (
            select(Task)
            .where(Task.status == status)
            .order_by(desc(Task.created_at))
            .limit(limit)
        )
    tasks = db.execute(stmt).scalars().all()
    return [build_summary(t) for t in tasks]


@router.post("/bulk-delete", response_model=BulkDeleteTasksResponse)
def bulk_delete_tasks(
    payload: BulkDeleteTasksRequest, db: Session = Depends(get_db)
) -> BulkDeleteTasksResponse:
    """批量删除任务。

    - 与单删一致：不限制状态（进行中的任务也会被删；worker 对已删除任务是安全退出）。
    - 材质 tag / 面料图 / 设计图 / 事件随 ORM 级联删除。
    - 不存在的 id 不算失败，在 `not_found` 里返回，便于前端提示。
    """
    ids = list(dict.fromkeys(payload.task_ids))  # 去重且保序
    tasks = db.execute(select(Task).where(Task.id.in_(ids))).scalars().all()

    found = {task.id for task in tasks}
    for task in tasks:
        db.delete(task)
    db.commit()

    return BulkDeleteTasksResponse(
        deleted=len(tasks),
        not_found=[task_id for task_id in ids if task_id not in found],
    )


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskDetail:
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/confirm-materials", response_model=TaskDetail)
def confirm_materials(
    task_id: str,
    payload: ConfirmMaterialsRequest,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> TaskDetail:
    task = _get_task(db, task_id)
    if not can_transition(task.status, TaskStatus.MATERIAL_SEARCH):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {task.status} 不支持确认材质",
        )

    for old in list(task.material_tags):
        db.delete(old)
    db.flush()

    for index, tag in enumerate(payload.tags):
        definition = get_definition(tag.material) or {}
        db.add(
            MaterialTag(
                task_id=task.id,
                material=tag.material,
                material_en=tag.material_en or definition.get("material_en", ""),
                confidence=tag.confidence,
                evidence=tag.evidence,
                category=tag.category or definition.get("category", ""),
                source=str(TagSource.USER),
                rank=index,
            )
        )
    db.commit()

    _advance(db, task, TaskStatus.MATERIAL_SEARCH)
    dispatcher.dispatch_material_search(task.id)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/select-materials", response_model=TaskDetail)
def select_materials(
    task_id: str,
    payload: SelectMaterialsRequest,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> TaskDetail:
    task = _get_task(db, task_id)
    if TaskStatus(task.status) not in _SELECT_STATES:
        raise HTTPException(
            status_code=409, detail=f"当前状态 {task.status} 不支持挑选材质图"
        )

    if payload.material_image_ids is not None:
        wanted = set(payload.material_image_ids)
        for image in task.material_images:
            image.selected = image.id in wanted

    target = orchestrator.mark_selection_and_advance(db, task)
    if target == TaskStatus.GENERATING:
        dispatcher.dispatch_generate(task.id)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/generate", response_model=TaskDetail)
def generate(
    task_id: str,
    payload: GenerateRequest,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> TaskDetail:
    task = _get_task(db, task_id)
    if not can_transition(task.status, TaskStatus.GENERATING):
        raise HTTPException(
            status_code=409, detail=f"当前状态 {task.status} 不支持生成设计图"
        )

    idea = payload.design_idea.strip()
    if idea:
        task.design_idea = idea
    elif not (task.design_idea or "").strip():
        raise HTTPException(status_code=400, detail="请填写设计想法")
    db.commit()

    _advance(db, task, TaskStatus.GENERATING)
    dispatcher.dispatch_generate(task.id, task.design_idea, payload.num_candidates)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/retry", response_model=TaskDetail)
def retry_task(
    task_id: str,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> TaskDetail:
    task = _get_task(db, task_id)
    if TaskStatus(task.status) != TaskStatus.FAILED:
        raise HTTPException(status_code=409, detail="仅失败任务可重试")
    task.status = str(TaskStatus.PENDING)
    task.error = None
    task.updated_at = _now()
    db.commit()

    dispatcher.dispatch_identify(task.id)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db)) -> None:
    task = _get_task(db, task_id)
    db.delete(task)
    db.commit()

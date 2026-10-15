"""任务相关接口：创建 / 查询 / 人工检查点 / 生成。

流水线：
  POST   /api/tasks                       勾选 N 张图 → 创建 N 个任务（并发识别）
  GET    /api/tasks                       任务列表（看板）
  GET    /api/tasks/{id}                  任务详情
  PUT    /api/tasks/{id}/material-card     编辑材质卡片（局部更新，不推进状态）
  POST   /api/tasks/{id}/confirm-materials ★检查点1：确认卡片 → 触发面料图检索
  POST   /api/tasks/{id}/material-images   编辑入口2：上传面料图（进参考图池）
  DELETE /api/tasks/{id}/material-images/{image_id}
  POST   /api/tasks/{id}/select-materials  ★检查点2：挑选面料图
  POST   /api/tasks/{id}/generate          ★检查点3：填设计想法 → 生成设计图
  POST   /api/tasks/{id}/retry            失败重试
  DELETE /api/tasks/{id}
  POST   /api/tasks/bulk-delete          批量删除（按 id 列表）
  GET    /api/tasks/{id}/events           SSE 进度流
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import MaterialImage, Task
from app.db.session import get_db
from app.enums import MaterialImageOrigin, TaskStatus
from app.schemas import (
    BulkDeleteTasksRequest,
    BulkDeleteTasksResponse,
    CreateTasksRequest,
    CreateTasksResponse,
    GenerateRequest,
    MaterialCardUpdateRequest,
    SelectMaterialsRequest,
    TaskDetail,
    TaskSummary,
)
from app.tasks import orchestrator
from app.tasks.dispatcher import get_dispatcher
from app.tasks.persist import persist_bytes
from app.tasks.serialize import build_detail, build_summary
from app.tasks.state_machine import can_transition

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_SELECT_STATES = {
    TaskStatus.AWAIT_MATERIAL_SELECT,
    TaskStatus.AWAIT_DESIGN_IDEA,
    TaskStatus.DONE,
}

#: 允许改卡片 / 传面料图的状态（识别中、生成中的中间态不允许，避免和 worker 抢写）
_CARD_EDITABLE_STATES = {
    TaskStatus.AWAIT_MATERIAL_CONFIRM,
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
    - 材质卡片 / 面料图 / 设计图 / 事件随 ORM 级联删除。
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


@router.put("/{task_id}/material-card", response_model=TaskDetail)
def update_material_card(
    task_id: str,
    payload: MaterialCardUpdateRequest,
    db: Session = Depends(get_db),
) -> TaskDetail:
    """编辑入口 1「改属性」+ 入口 3「写文字」：局部更新材质卡片。

    只写库、不推进状态 —— 用户可能改好几次才确认。确认走 `confirm-materials`。
    """
    task = _get_task(db, task_id)
    if task.material_card is None:
        raise HTTPException(status_code=404, detail="该任务还没有材质卡片")
    if TaskStatus(task.status) not in _CARD_EDITABLE_STATES:
        raise HTTPException(
            status_code=409, detail=f"当前状态 {task.status} 不支持编辑材质卡片"
        )

    patch = payload.model_dump(exclude_unset=True, exclude_none=True)
    if patch:
        orchestrator.update_material_card(db, task, patch)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/confirm-materials", response_model=TaskDetail)
def confirm_materials(
    task_id: str,
    db: Session = Depends(get_db),
    dispatcher=Depends(get_dispatcher),
) -> TaskDetail:
    """★检查点 1：确认材质卡片 → 按卡片检索面料图。

    卡片编辑在 `PUT /material-card`；本接口只做「确认 + 推进」，无请求体。
    """
    task = _get_task(db, task_id)
    if task.material_card is None:
        raise HTTPException(status_code=400, detail="该任务还没有材质卡片，无法确认")
    if not can_transition(task.status, TaskStatus.MATERIAL_SEARCH):
        raise HTTPException(
            status_code=409,
            detail=f"当前状态 {task.status} 不支持确认材质",
        )

    orchestrator.mark_card_confirmed(db, task)
    _advance(db, task, TaskStatus.MATERIAL_SEARCH)
    dispatcher.dispatch_material_search(task.id)
    db.expire_all()
    return build_detail(_get_task(db, task_id))


@router.post("/{task_id}/material-images", response_model=TaskDetail)
async def upload_material_images(
    task_id: str,
    files: list[UploadFile] = File(..., description="用户上传的面料图（可多张）"),
    db: Session = Depends(get_db),
) -> TaskDetail:
    """编辑入口 2「换小样」：上传面料图 → 直接进参考图池参与生图。

    与检索结果同在 `material_image` 池里；重跑检索**只清 origin=search 的行**，
    故上传图不会被覆盖。
    """
    task = _get_task(db, task_id)
    if TaskStatus(task.status) not in _CARD_EDITABLE_STATES:
        raise HTTPException(
            status_code=409, detail=f"当前状态 {task.status} 不支持上传面料图"
        )

    max_bytes = get_settings().download_max_bytes
    next_rank = max((m.rank for m in task.material_images), default=-1) + 1
    saved = 0
    for index, upload in enumerate(files):
        data = await upload.read()
        if not data:
            continue
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"图片过大（{len(data)} 字节），上限 {max_bytes} 字节",
            )
        persisted = persist_bytes("materials", data, upload.content_type or "image/png")
        db.add(
            MaterialImage(
                task_id=task.id,
                label=orchestrator.UPLOAD_LABEL,
                image_url=persisted.image_url,
                thumbnail_url=persisted.thumbnail_url,
                storage_key=persisted.storage_key,
                similarity=1.0,
                selected=True,
                rank=next_rank + index,
                origin=str(MaterialImageOrigin.UPLOAD),
            )
        )
        saved += 1

    if not saved:
        raise HTTPException(status_code=400, detail="没有读到有效的图片内容")
    db.commit()
    return build_detail(_get_task(db, task_id))


@router.delete("/{task_id}/material-images/{image_id}", response_model=TaskDetail)
def delete_material_image(
    task_id: str, image_id: str, db: Session = Depends(get_db)
) -> TaskDetail:
    """从参考图池里移除一张面料图（检索结果与上传图都可移除）。"""
    task = _get_task(db, task_id)
    image = next((m for m in task.material_images if m.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail=f"面料图不存在: {image_id}")
    db.delete(image)
    db.commit()
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
    # 与 design_idea 同样的部分更新语义：None = 保持任务上的已有值
    if payload.use_reference is not None:
        task.use_reference = payload.use_reference
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

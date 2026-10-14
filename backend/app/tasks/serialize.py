"""ORM → API 输出模型的转换。"""

from __future__ import annotations

from app.db.models import Task
from app.schemas import (
    ClothingImageOut,
    DesignImageOut,
    MaterialImageOut,
    MaterialTagOut,
    TaskDetail,
    TaskEventOut,
    TaskSummary,
)


def build_summary(task: Task) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        status=task.status,
        error=task.error,
        design_idea=task.design_idea or "",
        auto_generate=task.auto_generate,
        require_material_selection=task.require_material_selection,
        clothing_image=ClothingImageOut.model_validate(task.clothing_image),
        tag_count=len(task.material_tags),
        material_image_count=len(task.material_images),
        design_image_count=len(task.design_images),
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


def build_detail(task: Task, *, include_events: bool = True) -> TaskDetail:
    summary = build_summary(task)
    return TaskDetail(
        **summary.model_dump(),
        material_tags=[
            MaterialTagOut.model_validate(t) for t in task.material_tags
        ],
        material_images=[
            MaterialImageOut.model_validate(m) for m in task.material_images
        ],
        design_images=[
            DesignImageOut.model_validate(d) for d in task.design_images
        ],
        events=(
            [
                TaskEventOut.model_validate(e)
                for e in sorted(task.events, key=lambda e: e.created_at)
            ]
            if include_events
            else []
        ),
    )

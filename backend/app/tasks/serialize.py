"""ORM → API 输出模型的转换。"""

from __future__ import annotations

from app.abilities.material_identify.card_normalize import from_payload
from app.db.models import Task
from app.schemas import (
    BehaviorOut,
    ClothingImageOut,
    ColorOut,
    DesignImageOut,
    FabricOut,
    MaterialCardOut,
    MaterialImageOut,
    MaterialRegionOut,
    OpticalOut,
    PatternOut,
    RegionConfidenceOut,
    SwatchOut,
    TaskDetail,
    TaskEventOut,
    TaskSummary,
)


def _card_out(task: Task) -> MaterialCardOut | None:
    """卡片行 → API 输出。

    字段归属（避免两处真值）：
    - `payload` 列（JSON）→ `regions`（嵌套属性 + 逐字段置信度）
    - 其余独立列 → 品类 / 备注 / 依据 / 总体置信度 / 小样 / 纹理指纹引用
    """
    row = task.material_card
    if row is None:
        return None

    card = from_payload(row.payload)
    regions = [
        MaterialRegionOut(
            region_id=region.region_id,
            region_type=region.region_type,
            color=ColorOut(
                dominant_hex=region.color.dominant_hex,
                dominant_name=region.color.dominant_name,
                lab=list(region.color.lab) if region.color.lab else None,
                palette=region.color.palette,
                distribution=region.color.distribution,
            ),
            pattern=PatternOut(
                type=region.pattern.type,
                scale=region.pattern.scale,
                direction=region.pattern.direction,
                layout=region.pattern.layout,
            ),
            optical=OpticalOut(
                gloss=region.optical.gloss,
                transparency=region.optical.transparency,
            ),
            fabric=FabricOut(
                material=region.fabric.material,
                material_en=region.fabric.material_en,
                category=region.fabric.category,
                finish=region.fabric.finish,
                confidence=region.fabric.confidence,
            ),
            behavior=BehaviorOut(
                weight=region.behavior.weight,
                drape=region.behavior.drape,
                confidence=region.behavior.confidence,
                is_default=region.behavior.is_default,
            ),
            confidence=RegionConfidenceOut(
                color=region.confidence.color,
                pattern=region.confidence.pattern,
                gloss=region.confidence.gloss,
            ),
        )
        for region in card.regions
    ]

    return MaterialCardOut(
        id=row.id,
        task_id=row.task_id,
        source=row.source,
        category=row.category,
        regions=regions,
        evidence=row.evidence,
        note=row.note,
        schema_version=card.schema_version,
        overall_confidence=row.overall_confidence,
        swatch=SwatchOut(
            url=row.swatch_url,
            thumbnail_url=row.swatch_thumbnail_url,
            crop_box=list(row.swatch_crop_box) if row.swatch_crop_box else None,
            texture_embedding_ref=row.texture_embedding_ref,
        ),
        updated_at=row.updated_at,
    )


def build_summary(task: Task) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        status=task.status,
        error=task.error,
        design_idea=task.design_idea or "",
        auto_generate=task.auto_generate,
        require_material_selection=task.require_material_selection,
        use_reference=task.use_reference,
        clothing_image=ClothingImageOut.model_validate(task.clothing_image),
        has_material_card=task.material_card is not None,
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
        material_card=_card_out(task),
        material_images=[
            MaterialImageOut.model_validate(m) for m in task.material_images
        ],
        design_images=[DesignImageOut.model_validate(d) for d in task.design_images],
        events=(
            [
                TaskEventOut.model_validate(e)
                for e in sorted(task.events, key=lambda e: e.created_at)
            ]
            if include_events
            else []
        ),
    )

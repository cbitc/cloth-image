"""任务编排器：串起四个能力，逐阶段推进状态机并记录事件。

每个 run_* 函数都是「可重入的单阶段执行」，因此既能被后台线程池调用，
也能被测试直接同步调用。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.abilities.base import (
    MaterialCardResult,
    MaterialImageResult,
    MaterialQuery,
    ReferenceImage,
)
from app.abilities.material_identify.card_normalize import (
    attach_swatch,
    from_payload,
    to_payload,
)
from app.abilities.prompting import build_material_summary
from app.abilities.registry import get_abilities
from app.config import get_settings
from app.db.models import (
    ClothingImage,
    DesignImage,
    MaterialCard,
    MaterialImage,
    Task,
    TaskEvent,
)
from app.db.session import SessionLocal
from app.enums import MaterialImageOrigin, MaterialSource, TaskStatus
from app.storage import get_storage
from app.tasks import cache
from app.tasks.fetch import fetch_image_bytes, mirror_image
from app.tasks.persist import PersistedImage, persist_bytes, resolve_image
from app.tasks.state_machine import (
    STAGE_PROGRESS,
    assert_transition,
    can_transition,
    next_after_material_search,
)
from app.taxonomy import match_material

logger = logging.getLogger(__name__)

#: 用户上传的面料图在池子里的标签（与检索结果的「材质名」区分开）
UPLOAD_LABEL = "上传的面料图"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _emit(
    db: Session,
    task: Task,
    stage: str,
    message: str,
    progress: float | None = None,
) -> None:
    status = TaskStatus(task.status)
    db.add(
        TaskEvent(
            task_id=task.id,
            stage=stage,
            status=status,
            message=message,
            progress=STAGE_PROGRESS.get(status, 0.0) if progress is None else progress,
        )
    )


def _set_status(db: Session, task: Task, target: TaskStatus) -> None:
    current = TaskStatus(task.status)
    if current == target:  # 幂等：级联调用时可能已处于目标状态
        task.updated_at = _now()
        return
    assert_transition(current, target)
    task.status = str(target)
    task.updated_at = _now()
    if target == TaskStatus.DONE:
        task.completed_at = _now()
        task.error = None


def _fail(db: Session, task_id: str, exc: Exception) -> None:
    """回滚未提交的改动并把任务标记为 FAILED。"""
    logger.exception("任务 %s 失败", task_id)
    db.rollback()
    task = db.get(Task, task_id)
    if task is None:
        return
    if can_transition(task.status, TaskStatus.FAILED):
        task.status = str(TaskStatus.FAILED)
    task.error = f"{type(exc).__name__}: {exc}"
    task.updated_at = _now()
    task.completed_at = _now()
    db.add(
        TaskEvent(
            task_id=task.id,
            stage="error",
            status=TaskStatus.FAILED,
            message=task.error,
            progress=1.0,
        )
    )
    db.commit()


# --------------------------------------------------------------------------- #
# 任务创建
# --------------------------------------------------------------------------- #
def create_tasks(
    db: Session,
    clothing_image_ids: list[str],
    *,
    design_idea: str = "",
    auto_generate: bool = False,
    require_material_selection: bool = False,
) -> list[Task]:
    """用户勾选 N 张图 → 生成 N 个任务。"""
    tasks: list[Task] = []
    for cid in clothing_image_ids:
        if db.get(ClothingImage, cid) is None:
            continue
        task = Task(
            clothing_image_id=cid,
            status=str(TaskStatus.PENDING),
            design_idea=design_idea,
            auto_generate=auto_generate,
            require_material_selection=require_material_selection,
        )
        db.add(task)
        tasks.append(task)
    db.commit()
    for task in tasks:
        db.refresh(task)
    return tasks


def _hash_bytes(data: bytes | None) -> str:
    """图片内容哈希（与 persist 用同一算法），用于识别缓存。"""
    if not data:
        return ""
    return hashlib.sha256(data).hexdigest()[:32]


def _usage_suffix(model: str | None, usage: dict | None) -> str:
    """把模型名与 token 用量拼成事件文案后缀，便于从日志估算成本。"""
    parts: list[str] = []
    if model:
        parts.append(f"模型 {model}")
    if usage and usage.get("total_tokens"):
        parts.append(f"tokens {usage['total_tokens']}")
    return f"（{'，'.join(parts)}）" if parts else ""


def _load_source_image(
    db: Session, task: Task, clothing: ClothingImage
) -> tuple[bytes | None, str]:
    """取原服装图字节：优先自有存储 → 外链下载 → 失败则只传 URL 给模型。"""
    if clothing.storage_key:
        data = get_storage().get_bytes(clothing.storage_key)
        if data:
            return data, "image/png"

    if clothing.image_url.startswith(("http://", "https://")):
        try:
            return fetch_image_bytes(clothing.image_url)
        except Exception as exc:  # noqa: BLE001 - 下载失败不应阻断识别
            _emit(
                db,
                task,
                "identify",
                f"外部图片下载失败，改为直接把 URL 交给模型：{exc}",
            )
    return None, "image/png"


def _load_reference_bytes(
    db: Session, task: Task, storage_key: str, image_url: str, label: str
) -> bytes | None:
    """取参考图字节：自有存储 → 外链按需下载（仅内存，不落盘）。

    外链型 provider（如 Unsplash）只给 URL 不给字节，落库时 `storage_key` 为空；
    而 ComfyUI 这类「只吃上传字节」的生图实现取不到外链，会直接丢掉参考图。
    这里在生图前按需下载补齐，展示仍走外链（Unsplash 要求热链，故不回写 storage_key）。

    下载失败不阻断生图：降级为只把 URL 交给 provider（OpenAI 兼容端点可直接用 URL）；
    真正被丢弃的参考图由 provider 记进 `last_skipped_refs`，再由编排器转成任务事件。
    """
    if storage_key:
        data = get_storage().get_bytes(storage_key)
        if data:
            return data

    if image_url.startswith(("http://", "https://")):
        try:
            data, _ = fetch_image_bytes(image_url)
            return data
        except Exception as exc:  # noqa: BLE001 - 下载失败不应阻断生图
            logger.warning("%s 外链下载失败，将只传 URL：%s", label, exc)
    return None


def _persist_generated_image(db: Session, task: Task, result) -> PersistedImage:
    """生成图落盘。

    生图返回的是 OSS 临时地址，**必须镜像到自有存储**，否则过一段时间静默 404。
    """
    if result.image_bytes:
        return persist_bytes(
            "designs", result.image_bytes, result.content_type or "image/png"
        )
    if result.external_url:
        mirrored = mirror_image(result.external_url, "designs")
        if not mirrored.storage_key:
            _emit(
                db,
                task,
                "generate",
                "生成图镜像失败，已降级为引用外部临时地址（该地址可能过期）",
            )
        return mirrored
    raise ValueError("生成结果既无图片字节也无 URL")


# --------------------------------------------------------------------------- #
# 材质卡片：读写 / 用户编辑 / 检索锚
# --------------------------------------------------------------------------- #
def _load_card(task: Task) -> MaterialCardResult | None:
    """把任务的卡片行还原成 DTO（没有卡片时返回 None）。"""
    row = task.material_card
    return from_payload(row.payload) if row is not None else None


def _card_brief(card: MaterialCardResult) -> str:
    """一行摘要，用于任务事件文案。"""
    region = card.primary
    if region is None:
        return "空卡片"
    parts = [card.category or "未定品类"]
    if region.color.dominant_hex:
        parts.append(f"主色 {region.color.dominant_hex}")
    if region.pattern.type:
        parts.append(f"图案 {region.pattern.type}")
    if region.optical.gloss:
        parts.append(f"光泽 {region.optical.gloss}")
    if region.fabric.material:
        parts.append(f"面料 {region.fabric.material}")
    return "｜".join(parts)


def _save_card(
    db: Session, task: Task, card: MaterialCardResult, *, source: MaterialSource
) -> MaterialCard:
    """把卡片写进任务（存在则更新，不新建）。

    小样是真实图片：有字节就落盘并更新 URL / 裁剪框；没有字节（如用户只改属性）
    就保留原有小样，不会因为编辑一次卡片就丢掉保真锚点。
    """
    row = task.material_card
    if row is None:
        row = MaterialCard(task_id=task.id)
        task.material_card = row

    row.source = str(source)
    row.category = card.category
    row.payload = to_payload(card)
    row.note = card.note
    row.evidence = card.evidence
    row.overall_confidence = card.overall_confidence
    row.texture_embedding_ref = card.texture_embedding_ref

    region = card.primary
    if region is not None and region.swatch_bytes:
        persisted = persist_bytes(
            "swatches", region.swatch_bytes, region.swatch_content_type
        )
        row.swatch_url = persisted.image_url
        row.swatch_thumbnail_url = persisted.thumbnail_url
        row.swatch_storage_key = persisted.storage_key
        row.swatch_crop_box = (
            list(region.swatch_crop_box) if region.swatch_crop_box else None
        )

    db.flush()
    return row


def material_queries(card: MaterialCardResult | None) -> list[MaterialQuery]:
    """材质卡片 → 材质图检索锚（面料名为主锚，颜色 / 图案 / 光泽为增强）。

    卡片没有面料名时返回空列表：宁可一张不搜，也不要拿「纯色 哑光」这类词
    去搜出一堆泛泛的图片（MVP 期面料名由 VLM 从受控词表给出）。
    """
    if card is None:
        return []

    queries: list[MaterialQuery] = []
    for rank, region in enumerate(card.regions):
        material = (region.fabric.material or "").strip()
        if not material:
            continue
        queries.append(
            MaterialQuery(
                material=material,
                material_en=region.fabric.material_en,
                color=region.color.dominant_name,
                pattern=region.pattern.type,
                gloss=region.optical.gloss,
                rank=rank,
            )
        )
    return queries


def update_material_card(
    db: Session,
    task: Task,
    patch: dict,
    *,
    source: MaterialSource = MaterialSource.USER,
) -> MaterialCard:
    """把用户编辑合并进卡片（局部更新：patch 里出现什么就改什么）。

    `patch` 由 `MaterialCardUpdateRequest.model_dump(exclude_unset=True, exclude_none=True)`
    生成，故「没传」与「显式传 null」都不会出现在这里；传空字符串则会生效（用于清空备注）。
    """
    card = _load_card(task)
    if card is None:
        raise ValueError("该任务还没有材质卡片")

    region = card.primary

    if patch.get("category") is not None:
        card.category = str(patch["category"])
    if patch.get("note") is not None:
        card.note = str(patch["note"])
    if patch.get("evidence") is not None:
        card.evidence = str(patch["evidence"])

    region_patch = patch.get("region") or {}
    if region is not None:
        for field in ("color", "pattern", "optical", "behavior"):
            values = region_patch.get(field) or {}
            target = getattr(region, field)
            for key, value in values.items():
                setattr(target, key, value)

        fabric_patch = region_patch.get("fabric") or {}
        if fabric_patch:
            for key, value in fabric_patch.items():
                setattr(region.fabric, key, value)
            # 用户改了面料名：英文名 / 分类按受控词表补齐（未显式传时才覆盖）
            if "material" in fabric_patch:
                definition = match_material(
                    region.fabric.material, region.fabric.material_en
                )
                if definition:
                    if "material" in fabric_patch:
                        region.fabric.material = definition["material"]
                    if "material_en" not in fabric_patch:
                        region.fabric.material_en = definition.get("material_en", "")
                    if "category" not in fabric_patch:
                        region.fabric.category = definition.get("category", "")

    row = _save_card(db, task, card, source=source)
    _emit(db, task, "identify", "已更新材质卡片")
    db.commit()
    return row


def mark_card_confirmed(db: Session, task: Task) -> None:
    """检查点 1 完成：卡片来源标为 user（人工确认过），并记事件。"""
    row = task.material_card
    if row is not None:
        row.source = str(MaterialSource.USER)
        row.updated_at = _now()
    _emit(db, task, "identify", "已确认材质卡片，开始检索面料图")
    db.commit()


# --------------------------------------------------------------------------- #
# 阶段 1：识别材质
# --------------------------------------------------------------------------- #
def run_identify(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        try:
            _set_status(db, task, TaskStatus.IDENTIFYING)
            _emit(db, task, "identify", "开始识别服装材质…")
            db.commit()

            abilities = get_abilities()
            settings = get_settings()
            clothing = task.clothing_image
            identifier = abilities.material_identifier
            model_name = getattr(identifier, "model", None) or identifier.name

            image_bytes, content_type = _load_source_image(db, task, clothing)
            image_hash = clothing.image_hash or _hash_bytes(image_bytes)

            card: MaterialCardResult | None = None
            saved_tokens = 0
            if settings.identify_cache_enabled and image_hash:
                card, saved_tokens = cache.lookup(db, image_hash, model_name)

            cache_hit = card is not None
            if cache_hit:
                # 缓存只存语义部分：小样按缓存里的裁剪框从原图重裁（比存图便宜）
                attach_swatch(
                    card, image_bytes, max_side=settings.identify_swatch_max_side
                )
                _emit(
                    db,
                    task,
                    "identify",
                    "命中识别缓存（%s），跳过模型调用，省约 %d tokens"
                    % (model_name, saved_tokens),
                )
            else:
                card = identifier.identify(
                    image_bytes=image_bytes,
                    content_type=content_type,
                    image_url=clothing.image_url,
                    context_title=clothing.title,
                )
                if settings.identify_cache_enabled and image_hash and card.regions:
                    usage = getattr(identifier, "last_usage", None) or {}
                    cache.store(
                        db,
                        image_hash,
                        model_name,
                        card,
                        int(usage.get("total_tokens") or 0),
                    )

            _save_card(db, task, card, source=MaterialSource.AI)

            _set_status(db, task, TaskStatus.AWAIT_MATERIAL_CONFIRM)
            _emit(
                db,
                task,
                "identify",
                "识别完成：%s，等待人工确认%s"
                % (
                    _card_brief(card),
                    ""
                    if cache_hit
                    else _usage_suffix(
                        getattr(abilities.material_identifier, "model", None),
                        getattr(abilities.material_identifier, "last_usage", None),
                    ),
                ),
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            _fail(db, task_id, exc)


# --------------------------------------------------------------------------- #
# 阶段 2：检索材质图
# --------------------------------------------------------------------------- #
def run_material_search(task_id: str, *, cascade: bool = True) -> None:
    settings = get_settings()
    goto_generate = False
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        try:
            _set_status(db, task, TaskStatus.MATERIAL_SEARCH)
            _emit(db, task, "material_search", "按卡片里的面料名检索面料图…")
            db.commit()

            abilities = get_abilities()
            queries = material_queries(_load_card(task))
            if not queries:
                _emit(
                    db,
                    task,
                    "material_search",
                    "材质卡片缺少面料名，已跳过面料图检索（可在卡片里补充面料后重试）",
                )
            results = abilities.material_search.search(
                queries, per_tag=settings.material_images_per_tag
            )

            # 只清「检索来的」：用户上传的面料图必须保留（重跑检索不该丢掉用户输入）
            kept = 0
            for old in list(task.material_images):
                if old.origin == str(MaterialImageOrigin.UPLOAD):
                    kept += 1
                    continue
                db.delete(old)
            db.flush()

            for result in results:
                persisted = resolve_image(
                    "materials",
                    result.image_bytes,
                    result.external_url,
                    result.content_type,
                )
                db.add(
                    MaterialImage(
                        task_id=task.id,
                        label=result.label,
                        image_url=persisted.image_url,
                        thumbnail_url=persisted.thumbnail_url,
                        storage_key=persisted.storage_key,
                        source_url=result.source_url,
                        similarity=result.similarity,
                        selected=True,
                        rank=result.rank,
                        origin=str(MaterialImageOrigin.SEARCH),
                    )
                )

            target = next_after_material_search(
                require_selection=task.require_material_selection,
                auto_generate=task.auto_generate,
                has_idea=bool((task.design_idea or "").strip()),
            )
            _set_status(db, task, target)
            _emit(
                db,
                task,
                "material_search",
                "检索到 %d 张面料图%s"
                % (len(results), f"，另有 {kept} 张用户上传图" if kept else ""),
            )
            db.commit()
            goto_generate = target == TaskStatus.GENERATING
        except Exception as exc:  # noqa: BLE001
            _fail(db, task_id, exc)

    if goto_generate and cascade:
        run_generate(task_id)


def mark_selection_and_advance(db: Session, task: Task) -> TaskStatus:
    """检查点 2 完成：确认材质图选择后推进状态（返回下一状态）。"""
    selected = sum(1 for m in task.material_images if m.selected)
    target = next_after_material_search(
        require_selection=False,
        auto_generate=task.auto_generate,
        has_idea=bool((task.design_idea or "").strip()),
    )
    _set_status(db, task, target)
    _emit(db, task, "material_search", f"已确认 {selected} 张面料图")
    db.commit()
    return target


# --------------------------------------------------------------------------- #
# 阶段 3：图生图
# --------------------------------------------------------------------------- #
def run_generate(
    task_id: str,
    design_idea: str | None = None,
    num_candidates: int | None = None,
) -> None:
    settings = get_settings()
    num_candidates = num_candidates or settings.design_candidates
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        try:
            if design_idea is not None:
                task.design_idea = design_idea
            _set_status(db, task, TaskStatus.GENERATING)
            _emit(db, task, "generate", "正在生成设计图…")
            db.commit()

            abilities = get_abilities()
            selected = [m for m in task.material_images if m.selected]
            material_images = [
                MaterialImageResult(
                    label=m.label,
                    similarity=m.similarity,
                    content_type="image/png",
                    # 带上字节：外部生图服务访问不到我们的 localhost /media 地址；
                    # 外链型 provider（如 Unsplash）没有本地字节 → 按需下载补齐，
                    # 否则只吃字节的生图实现（ComfyUI）会把这些参考图丢掉。
                    image_bytes=_load_reference_bytes(
                        db, task, m.storage_key, m.image_url, f"材质图({m.label})"
                    ),
                    external_url=m.image_url,
                    rank=m.rank,
                )
                for m in selected
            ]

            clothing = task.clothing_image
            reference: ReferenceImage | None
            if task.use_reference:
                ref_bytes, _ = _load_source_image(db, task, clothing)
                reference = ReferenceImage(
                    image_bytes=ref_bytes,
                    external_url=clothing.image_url,
                    caption=clothing.title,
                )
            else:
                # 用户明确选择不参考原图：连下载都省掉，退化为「材质图 + 文字描述版型」
                reference = None
                _emit(
                    db,
                    task,
                    "generate",
                    "本次不参考原服装图：仅按材质图与设计想法生成",
                )

            if reference is None and not any(m.image_bytes for m in material_images):
                # 既没有原图也没有可用的材质图字节 → 实际会退化成纯文生图，提前告知
                _emit(
                    db,
                    task,
                    "generate",
                    "没有任何可用参考图（未参考原图，材质图也无本地字节），本次退化为纯文生图",
                )

            card = _load_card(task)
            results = abilities.design_generator.generate(
                material_images,
                task.design_idea or "",
                reference,
                num_candidates,
                material_summary=build_material_summary(card) if card else "",
            )

            # provider 自报被丢弃的参考图（无字节 / 超上限 / 本机地址）→ 让用户看得见
            skipped = list(
                getattr(abilities.design_generator, "last_skipped_refs", None) or []
            )
            if skipped:
                _emit(
                    db,
                    task,
                    "generate",
                    "部分参考图未生效：" + "；".join(skipped),
                )

            for old in list(task.design_images):
                db.delete(old)
            db.flush()

            for result in results:
                persisted = _persist_generated_image(db, task, result)
                db.add(
                    DesignImage(
                        task_id=task.id,
                        image_url=persisted.image_url,
                        thumbnail_url=persisted.thumbnail_url,
                        storage_key=persisted.storage_key,
                        prompt=result.prompt,
                        negative_prompt=result.negative_prompt,
                        model=result.model,
                        seed=result.seed,
                        rank=result.rank,
                        used_reference=result.used_reference,
                    )
                )

            _set_status(db, task, TaskStatus.DONE)
            _emit(
                db,
                task,
                "generate",
                "生成 %d 张设计图%s"
                % (
                    len(results),
                    _usage_suffix(
                        getattr(abilities.design_generator, "model", None),
                        getattr(abilities.design_generator, "last_usage", None),
                    ),
                ),
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            _fail(db, task_id, exc)

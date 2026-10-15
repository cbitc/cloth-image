"""任务编排器：串起四个能力，逐阶段推进状态机并记录事件。

每个 run_* 函数都是「可重入的单阶段执行」，因此既能被后台线程池调用，
也能被测试直接同步调用。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.abilities.base import MaterialImageResult, MaterialTagResult, ReferenceImage
from app.abilities.registry import get_abilities
from app.config import get_settings
from app.db.models import (
    ClothingImage,
    DesignImage,
    MaterialImage,
    MaterialTag,
    Task,
    TaskEvent,
)
from app.db.session import SessionLocal
from app.enums import TagSource, TaskStatus
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
from app.taxonomy import get_definition

logger = logging.getLogger(__name__)


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

            tags: list[MaterialTagResult] = []
            saved_tokens = 0
            cache_hit = False
            if settings.identify_cache_enabled and image_hash:
                tags, saved_tokens = cache.lookup(db, image_hash, model_name)
                cache_hit = bool(tags)

            if cache_hit:
                _emit(
                    db,
                    task,
                    "identify",
                    "命中识别缓存（%s），跳过模型调用，省约 %d tokens"
                    % (model_name, saved_tokens),
                )
            else:
                tags = identifier.identify(
                    image_bytes=image_bytes,
                    content_type=content_type,
                    image_url=clothing.image_url,
                    context_title=clothing.title,
                )
                if settings.identify_cache_enabled and image_hash and tags:
                    usage = getattr(identifier, "last_usage", None) or {}
                    cache.store(
                        db,
                        image_hash,
                        model_name,
                        tags,
                        int(usage.get("total_tokens") or 0),
                    )

            for old in list(task.material_tags):
                db.delete(old)
            db.flush()

            for index, tag in enumerate(tags):
                definition = get_definition(tag.material) or {}
                db.add(
                    MaterialTag(
                        task_id=task.id,
                        material=tag.material,
                        material_en=tag.material_en
                        or definition.get("material_en", ""),
                        confidence=tag.confidence,
                        evidence=tag.evidence,
                        category=tag.category or definition.get("category", ""),
                        source=str(TagSource.AI),
                        rank=tag.rank or index,
                    )
                )

            _set_status(db, task, TaskStatus.AWAIT_MATERIAL_CONFIRM)
            _emit(
                db,
                task,
                "identify",
                "识别出 %d 个材质候选，等待人工确认%s"
                % (
                    len(tags),
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
            _emit(db, task, "material_search", "按材质 tag 检索面料图…")
            db.commit()

            abilities = get_abilities()
            tags = [
                MaterialTagResult(
                    material=t.material,
                    material_en=t.material_en,
                    confidence=t.confidence,
                    evidence=t.evidence,
                    category=t.category,
                    rank=t.rank,
                )
                for t in task.material_tags
            ]
            results = abilities.material_search.search(
                tags, per_tag=settings.material_images_per_tag
            )

            for old in list(task.material_images):
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
                        tag=result.tag,
                        image_url=persisted.image_url,
                        thumbnail_url=persisted.thumbnail_url,
                        storage_key=persisted.storage_key,
                        source_url=result.source_url,
                        similarity=result.similarity,
                        selected=True,
                        rank=result.rank,
                    )
                )

            target = next_after_material_search(
                require_selection=task.require_material_selection,
                auto_generate=task.auto_generate,
                has_idea=bool((task.design_idea or "").strip()),
            )
            _set_status(db, task, target)
            _emit(db, task, "material_search", f"检索到 {len(results)} 张面料图")
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
                    tag=m.tag,
                    similarity=m.similarity,
                    content_type="image/png",
                    # 带上字节：外部生图服务访问不到我们的 localhost /media 地址；
                    # 外链型 provider（如 Unsplash）没有本地字节 → 按需下载补齐，
                    # 否则只吃字节的生图实现（ComfyUI）会把这些参考图丢掉。
                    image_bytes=_load_reference_bytes(
                        db, task, m.storage_key, m.image_url, f"材质图({m.tag})"
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

            results = abilities.design_generator.generate(
                material_images,
                task.design_idea or "",
                reference,
                num_candidates,
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

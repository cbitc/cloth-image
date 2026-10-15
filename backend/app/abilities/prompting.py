"""Prompt 组装（各 provider 共用）。"""

from __future__ import annotations

from app.abilities.base import MaterialCardResult

NEGATIVE_PROMPT = (
    "低分辨率, 模糊, 变形, 多余的手指, 水印, 文字, 卡通, 塑料质感, 结构错乱"
)


def _color_phrase(color) -> str:
    name = (color.dominant_name or "").strip() or (color.dominant_hex or "").strip()
    if not name:
        return ""
    text = f"主色 {name}"
    if color.dominant_hex and color.dominant_hex.upper() != name.upper():
        text += f"（{color.dominant_hex}）"
    palette = color.palette[0] if color.palette else None
    if isinstance(palette, dict) and palette.get("ratio"):
        try:
            text += f"，占 {round(float(palette['ratio']) * 100)}%"
        except (TypeError, ValueError):
            pass
    if color.distribution:
        text += f"，{color.distribution}"
    return text


def build_material_summary(card: MaterialCardResult) -> str:
    """材质卡片 → 生图提示词里的「材质要求」文本。

    只编译**看得见、可执行**的要求：品类 / 主色 / 图案 / 光泽 / 面料 / 备注。
    设计想法（`design_idea`）是另一段，不要混进来。
    """
    region = card.primary
    if region is None:
        return ""

    parts: list[str] = []
    if card.category:
        parts.append(f"品类 {card.category}")

    color = _color_phrase(region.color)
    if color:
        parts.append(color)

    if region.pattern.type:
        pattern = f"图案 {region.pattern.type}"
        if region.pattern.scale:
            pattern += f"（尺度 {region.pattern.scale}）"
        if region.pattern.direction:
            pattern += f"（方向 {region.pattern.direction}）"
        parts.append(pattern)

    optical = " / ".join(
        value for value in (region.optical.gloss, region.optical.transparency) if value
    )
    if optical:
        parts.append(f"光学 {optical}")

    if region.fabric.material:
        parts.append(f"面料 {region.fabric.material}")

    behavior = " / ".join(
        value for value in (region.behavior.weight, region.behavior.drape) if value
    )
    if behavior:
        parts.append(f"手感 {behavior}")

    summary = "；".join(parts)
    note = (card.note or "").strip()
    if note:
        summary = f"{summary}；备注：{note}" if summary else f"备注：{note}"
    return summary


def build_design_prompt(
    *,
    material_summary: str,
    material_images_count: int,
    design_idea: str,
    has_reference: bool,
) -> str:
    """按设计方案 §2.4 的模式组装指令式编辑 prompt。

    **`material_images_count` / `has_reference` 必须是「实际送进模型」的量**，
    而不是候选数量：候选材质图可达十几个（材质锚 × 每锚张数），
    但参考图上限通常只有 3 张（`IMAGE_MAX_REFS` / `image1..3`）。
    若按候选数生成，prompt 会声称存在并不存在的「参考图N」→
    模型无法与真实图片对应，反而忽略材质/版型参考。

    `material_summary` 由 `build_material_summary(card)` 编译：它是**语义轨**的要求；
    材质图与 swatch 是**参考轨**，两者互补（改属性走语义，换小样走参考）。
    """
    idea = design_idea.strip() or "在保留原有版型的前提下优化设计"
    summary = (material_summary or "").strip()
    lines: list[str] = []

    if has_reference:
        lines.append("参考图1 = 原服装图（款式 / 版型参考）。")
    if material_images_count:
        # 原服装图占 1 号位→材质图从 2 号开始；没有原服装图时材质图从 1 号开始
        first = 2 if has_reference else 1
        last = first + material_images_count - 1
        span = f"参考图{first}" if first == last else f"参考图{first}~{last}"
        lines.append(f"{span} = 面料质感参考图。")

    subject = "参考图1的服装" if has_reference else "这件服装"
    lines.append(f"将{subject}重新设计：{idea}。")

    if material_images_count:
        tail = "，保留原服装的版型轮廓与比例" if has_reference else ""
        detail = f"材质要求：{summary}。" if summary else ""
        lines.append(f"面料改用上述参考图所示的面料质感{tail}。{detail}")
    elif summary:
        lines.append(f"面料按以下材质要求处理：{summary}。")
    else:
        lines.append("面料保持与原图一致的质感。")

    lines.append("输出高清服装设计效果图，真实面料质感，专业时尚摄影光。")
    return "\n".join(lines)


def build_material_query(tag: str) -> str:
    """材质名 → 面料特写检索词（含中英）。"""
    from app.taxonomy import build_material_query as _q

    return _q(tag)


__all__ = [
    "NEGATIVE_PROMPT",
    "build_design_prompt",
    "build_material_summary",
    "build_material_query",
]

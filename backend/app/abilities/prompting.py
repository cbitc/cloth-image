"""Prompt 组装（各 provider 共用）。"""

from __future__ import annotations

from collections.abc import Iterable

NEGATIVE_PROMPT = (
    "低分辨率, 模糊, 变形, 多余的手指, 水印, 文字, 卡通, 塑料质感, 结构错乱"
)


def build_design_prompt(
    *,
    material_tags: Iterable[str],
    material_images_count: int,
    design_idea: str,
    has_reference: bool,
) -> str:
    """按设计方案 §2.4 的模式组装指令式编辑 prompt。"""
    tags = "、".join(dict.fromkeys(t for t in material_tags if t)) or "未指定"
    lines = []
    if has_reference:
        lines.append("参考图1 = 原服装图（款式 / 版型参考）。")
    if material_images_count:
        lines.append(f"参考图2~{material_images_count + 1} = 识别出的材质图。")
    lines.append(
        f"将参考图1的服装重新设计：{design_idea.strip() or '在保留原有版型的前提下优化设计'}。"
    )
    lines.append(
        f"面料使用参考材质图所示的「{tags}」材质，保留参考图1的版型轮廓与比例。"
    )
    lines.append("输出高清服装设计效果图，真实面料质感，专业时尚摄影光。")
    return "\n".join(lines)


def build_material_query(tag: str) -> str:
    """材质 tag → 面料特写检索词（含中英）。"""
    from app.taxonomy import build_material_query as _q

    return _q(tag)


__all__ = ["NEGATIVE_PROMPT", "build_design_prompt", "build_material_query"]

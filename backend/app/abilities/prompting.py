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
    """按设计方案 §2.4 的模式组装指令式编辑 prompt。

    **`material_images_count` / `has_reference` 必须是「实际送进模型」的量**，
    而不是候选数量：候选材质图可达十几个（tag 数 × 每 tag 张数），
    但参考图上限通常只有 3 张（`IMAGE_MAX_REFS` / `image1..3`）。
    若按候选数生成，prompt 会声称存在并不存在的「参考图N」→
    模型无法与真实图片对应，反而忽略材质/版型参考。
    """
    tags = "、".join(dict.fromkeys(t for t in material_tags if t)) or "未指定"
    idea = design_idea.strip() or "在保留原有版型的前提下优化设计"
    lines: list[str] = []

    if has_reference:
        lines.append("参考图1 = 原服装图（款式 / 版型参考）。")
    if material_images_count:
        # 原服装图占 1 号位→材质图从 2 号开始；没有原服装图时材质图从 1 号开始
        first = 2 if has_reference else 1
        last = first + material_images_count - 1
        span = f"参考图{first}" if first == last else f"参考图{first}~{last}"
        lines.append(f"{span} = 识别出的材质图。")

    subject = "参考图1的服装" if has_reference else "这件服装"
    lines.append(f"将{subject}重新设计：{idea}。")
    if material_images_count:
        # 有原服装图时强调「保留版型」；否则只描述面料
        tail = "，保留原服装的版型轮廓与比例" if has_reference else ""
        lines.append(f"面料使用参考材质图所示的「{tags}」材质{tail}。")
    else:
        # 没有材质参考图时只把材质名作为文字要求，不要提「参考材质图」
        lines.append(f"面料使用「{tags}」材质。")
    lines.append("输出高清服装设计效果图，真实面料质感，专业时尚摄影光。")
    return "\n".join(lines)


def build_material_query(tag: str) -> str:
    """材质 tag → 面料特写检索词（含中英）。"""
    from app.taxonomy import build_material_query as _q

    return _q(tag)


__all__ = ["NEGATIVE_PROMPT", "build_design_prompt", "build_material_query"]

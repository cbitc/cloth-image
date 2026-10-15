"""候选面料图的颜色重排。

Unsplash 不返回相关性分数，`similarity` 原本只是个名次代理（`0.96 - 0.05*i`），
不做任何「与识别出的颜色是否一致」的校验 → 混进来的不搭图既不能被剔除也不能被降权。

这里引入一个可计算的信号：把卡片的主导色 / 色板当**目标色**，候选图主色做**感知色差**
（LAB ΔE）比对得到颜色分，再与名次先验加权成最终 `similarity`。

纯函数，便于脱离网络直接单测。
"""

from __future__ import annotations

from app.abilities.base import MaterialImageResult
from app.abilities.color_ops import color_similarity, delta_e, hex_to_lab

Lab = tuple[float, float, float]

#: 颜色分与名次先验的权重（准确优先：以颜色为主）
COLOR_WEIGHT = 0.6
#: 拿不到颜色信息（缩略图下载失败 / 无法解码）时的中性分：既不奖励也不惩罚，
#: 但要让它落到中游 —— 否则「没分析过的候选」会靠名次先验霸榜。
MISSING_COLOR_SCORE = 0.5


def target_labs(
    palette: list[dict] | None, color_hex: str = ""
) -> list[tuple[Lab, float]]:
    """色板 → 加权目标色（权重归一化）；色板为空时用主导色 hex 兜底。"""
    entries: list[tuple[Lab, float]] = []
    for item in palette or []:
        if not isinstance(item, dict):
            continue
        lab = hex_to_lab(str(item.get("hex") or ""))
        if lab is None:
            continue
        try:
            weight = max(0.0, float(item.get("ratio", 0.0)))
        except (TypeError, ValueError):
            weight = 0.0
        entries.append((lab, weight))

    if not entries and color_hex:
        lab = hex_to_lab(color_hex)
        if lab is not None:
            entries.append((lab, 1.0))

    if not entries:
        return []

    total = sum(weight for _, weight in entries)
    if total <= 0:
        even = round(1.0 / len(entries), 4)
        return [(lab, even) for lab, _ in entries]
    return [(lab, weight / total) for lab, weight in entries]


def color_score(
    colors: list[tuple[Lab, float]] | None, targets: list[tuple[Lab, float]]
) -> float | None:
    """候选图主色 vs 目标色 → 0~1；任一为空 → None（表示「没有颜色信息」）。"""
    if not colors or not targets:
        return None

    weighted_distance = 0.0
    for target, weight in targets:
        nearest = min(delta_e(target, candidate) for candidate, _ in colors)
        weighted_distance += weight * nearest
    return color_similarity(weighted_distance)


def rank_prior(index: int, total: int) -> float:
    """名次先验：图库返回顺序本身是相关性信号，只是不该是**唯一**信号。"""
    if total <= 1:
        return 1.0
    return 1.0 - index / total


def score_candidates(
    candidates: list[tuple[MaterialImageResult, list[tuple[Lab, float]] | None]],
    targets: list[tuple[Lab, float]],
) -> list[tuple[MaterialImageResult, float]]:
    """给候选打分并按分数降序返回。

    `candidates` 是 `(结果, 主色列表或 None)` 的有序序列（顺序 = 图库相关性）。
    """
    total = len(candidates)
    scored: list[tuple[MaterialImageResult, float]] = []
    for index, (result, colors) in enumerate(candidates):
        prior = rank_prior(index, total)
        similarity = color_score(colors, targets)
        effective = MISSING_COLOR_SCORE if similarity is None else similarity
        score = COLOR_WEIGHT * effective + (1.0 - COLOR_WEIGHT) * prior
        scored.append((result, round(min(1.0, max(0.0, score)), 2)))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored


__all__ = [
    "COLOR_WEIGHT",
    "MISSING_COLOR_SCORE",
    "target_labs",
    "color_score",
    "rank_prior",
    "score_candidates",
]

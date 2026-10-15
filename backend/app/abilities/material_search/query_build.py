"""材质卡片 → 英文检索词（让「上次识别出的信息」真正进入检索）。

此前实现里颜色 / 图案 / 光泽只有是 ASCII 时才拼进 query，而识别输出是**中文受控枚举**
（「深灰蓝」「纯色」「哑光」）→ 三个增强项实际全被丢弃，只用到了材质名。
这里改为「查表翻译 + 由 hex 推导英文色词」，并给出**有序的多查询变体**：
具体变体负责精度，材质名变体负责召回下限。
"""

from __future__ import annotations

from app.abilities.base import MaterialQuery
from app.abilities.color_ops import nearest_color_name
from app.taxonomy import build_material_query, gloss_en, pattern_en

#: 拼在材质名后的限定词，保证搜到的是面料特写而非成衣
DEFAULT_QUERY_SUFFIX = "fabric texture close up"
#: 每个检索锚最多几条查询（图库有频率限制，变体不是越多越好）
MAX_QUERY_VARIANTS = 2

_SOLID = "纯色"


def build_query_variants(
    query: MaterialQuery,
    *,
    suffix: str = DEFAULT_QUERY_SUFFIX,
    max_variants: int = MAX_QUERY_VARIANTS,
) -> list[str]:
    """把检索锚编译成**有序**的查询变体（越靠前越具体）。

    - 变体 1（有颜色 / 图案 / 光泽时）：`[{英文色词} {图案词} {光泽词}] {材质} fabric texture close up`
      · 图案是「纯色」时省略图案词（`solid` 无区分度），改把光泽词补上 —— 此时光泽才是主要视觉差异；
      · 其他图案则不加光泽词，避免词太多导致图库全不命中。
    - 变体 2：仅 `{材质} fabric texture close up`，保证召回下限。
    - 没有英文材质名 → 回退词表英文关键词；连材质名都没有 → 无查询。
    """
    material_en = (query.material_en or "").strip()
    if not material_en:
        return (
            [build_material_query(query.material)]
            if (query.material or "").strip()
            else []
        )

    base = f"{material_en} {suffix}".strip()

    pattern = (query.pattern or "").strip()
    pattern_word = "" if pattern in ("", _SOLID) else pattern_en(pattern)
    gloss_word = gloss_en(query.gloss) if pattern in ("", _SOLID) else ""

    color_word = nearest_color_name(query.color_hex)
    if not color_word:
        raw_color = (query.color or "").strip()
        # 模型偶尔直接给英文色名，此时它比 hex 推导更贴近图库用词
        if raw_color.isascii():
            color_word = raw_color

    variants: list[str] = []
    hints = [word for word in (color_word, pattern_word, gloss_word) if word]
    if hints:
        variants.append(f"{' '.join(hints)} {base}")
    variants.append(base)

    deduped: list[str] = []
    for text in variants:
        if text and text not in deduped:
            deduped.append(text)
    return deduped[: max(1, max_variants)]


__all__ = ["DEFAULT_QUERY_SUFFIX", "MAX_QUERY_VARIANTS", "build_query_variants"]

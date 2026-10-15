"""Unsplash 材质图检索（真实实现）。

与「服装图搜索」共用 `app/abilities/unsplash_client.py`；这里只负责两件事：
把材质卡片的检索锚变成「面料特写」检索词，以及把结果映射成 `MaterialImageResult`。

要点：
- 检索词优先用 `material_en`（Unsplash 以英文效果最好），否则回退词表里的英文关键词
  （`taxonomy.build_material_query`）。
- 颜色 / 图案 / 光泽是**可选**增强项：Unsplash 对中文命中率低，
  故只在它们是 ASCII（如模型给了英文）时才拼进 query。
- **每个锚一次请求**；demo 应用限 50 次/小时。
- Unsplash 不返回相关性分数：`similarity` 用**排名代理**（按名次递减），仅供排序展示。
- 官方要求热链 + 署名：原图页写进 `source_url`。
"""

from __future__ import annotations

from app.abilities.base import MaterialImageResult, MaterialQuery
from app.abilities.http import RetryingHttpClient
from app.abilities.unsplash_client import DEFAULT_BASE_URL, UnsplashClient
from app.taxonomy import build_material_query

#: 拼在材质名后的限定词，保证搜到的是面料特写而非成衣
DEFAULT_QUERY_SUFFIX = "fabric texture close up"


def _similarity(rank_in_tag: int, tag_rank: int) -> float:
    """Unsplash 无相关性分数 → 用排名代理（按名次递减，便于 UI 展示）。"""
    return round(max(0.35, 0.96 - 0.05 * rank_in_tag - 0.02 * tag_rank), 2)


class UnsplashMaterialSearchProvider:
    name = "unsplash"

    def __init__(
        self,
        access_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 90.0,
        max_retries: int = 3,
        http_client: RetryingHttpClient | None = None,
        query_suffix: str = DEFAULT_QUERY_SUFFIX,
    ) -> None:
        self._suffix = query_suffix
        self._client = UnsplashClient(
            access_key,
            base_url=base_url,
            timeout_s=timeout_s,
            max_retries=max_retries,
            http_client=http_client,
        )

    # ------------------------------------------------------------------ #
    # MaterialImageSearchProvider 协议
    # ------------------------------------------------------------------ #
    def search(
        self, queries: list[MaterialQuery], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        """按每个检索锚各检索 `per_tag` 张面料特写图。"""
        self._client.require_key("查找材质图")

        per_tag = max(1, per_tag)
        results: list[MaterialImageResult] = []
        rank = 0

        for query in queries:
            text = self._query_for(query)
            if not text:
                continue

            for index, photo in enumerate(self._client.search(text, per_tag)):
                results.append(
                    MaterialImageResult(
                        label=query.material,
                        similarity=_similarity(index, query.rank),
                        content_type="image/jpeg",
                        external_url=photo.image_url,
                        source_url=photo.page_url,
                        rank=rank,
                    )
                )
                rank += 1

        return results

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _query_for(self, query: MaterialQuery) -> str:
        material_en = (query.material_en or "").strip()
        if not material_en:
            # 词表里有英文关键词时用它；否则退化为「中文名 + fabric texture close-up」
            return build_material_query(query.material)

        # 中文增强词对 Unsplash 是噪声（实测中文命中率低），只拼 ASCII 的
        hints = " ".join(
            value
            for value in (query.color, query.pattern, query.gloss)
            if value and value.isascii()
        )
        base = f"{material_en} {self._suffix}".strip()
        return f"{hints} {base}".strip() if hints else base

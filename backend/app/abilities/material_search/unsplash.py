"""Unsplash 材质图检索（真实实现）。

与「服装图搜索」共用 `app/abilities/unsplash_client.py`；这里负责三件事：
把材质卡片的检索锚变成「面料特写」检索词、把结果映射成 `MaterialImageResult`，
以及在返回前**按识别出的颜色重排**候选。

要点：
- 检索词不再丢弃中文识别结果：图案 / 光泽查表翻译成英文，颜色由 `dominant_hex` 推导英文色词
  （见 `query_build`）；每个锚发「具体变体 + 材质名变体」共 ≤2 次请求。
- **只在拿到颜色信息时才过采样**（`per_tag * oversample`）：多取候选是为了重排时有得筛。
- 重排：下载候选缩略图算主色，与卡片色板比 LAB ΔE（见 `rerank`）；
  **下载失败 / 无法解码的候选不丢**，给中性分。
- 重排关闭或无颜色信息 → 保持图库顺序，`similarity` 退回名次代理（仅排序展示）。
- Unsplash 不返回相关性分数；官方要求热链 + 署名：原图页写进 `source_url`。
- demo 应用限 50 次/小时 —— 变体数、过采样倍数都受此约束。
"""

from __future__ import annotations

from app.abilities.base import MaterialImageResult, MaterialQuery
from app.abilities.color_ops import dominant_lab_colors
from app.abilities.http import ProviderError, RetryingHttpClient
from app.abilities.material_search.query_build import (
    DEFAULT_QUERY_SUFFIX,
    build_query_variants,
)
from app.abilities.material_search.rerank import score_candidates, target_labs
from app.abilities.unsplash_client import (
    DEFAULT_BASE_URL,
    MAX_PER_PAGE,
    UnsplashClient,
    UnsplashPhoto,
)

#: 下载缩略图做颜色分析的大小上限（缩略图本应很小，超限视为异常）
THUMB_MAX_BYTES = 3_000_000
#: 每张候选图取几个主色
THUMB_COLOR_COUNT = 4


def _similarity(rank_in_tag: int, tag_rank: int) -> float:
    """Unsplash 无相关性分数时的名次代理（仅用于「无颜色信息」的兜底排序）。"""
    return round(max(0.35, 0.96 - 0.05 * rank_in_tag - 0.02 * tag_rank), 2)


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
        rerank_enabled: bool = True,
        oversample: int = 3,
        rerank_max: int = 12,
    ) -> None:
        self._suffix = query_suffix
        self._rerank_enabled = rerank_enabled
        self._oversample = max(1, oversample)
        self._rerank_max = max(1, rerank_max)
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
        """按每个检索锚各返回 `per_tag` 张面料特写图（内部已按颜色重排）。"""
        self._client.require_key("查找材质图")

        per_tag = max(1, per_tag)
        results: list[MaterialImageResult] = []
        rank = 0

        for query in queries:
            for result in self._candidates(query, per_tag):
                result.rank = rank
                rank += 1
                results.append(result)

        return results

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _candidates(
        self, query: MaterialQuery, per_tag: int
    ) -> list[MaterialImageResult]:
        """单个检索锚：发变体请求 → 过采样 → （可选）颜色重排 → 取前 `per_tag`。"""
        variants = build_query_variants(query, suffix=self._suffix)
        if not variants:
            return []

        targets = (
            target_labs(query.palette, query.color_hex) if self._rerank_enabled else []
        )
        # 没有可用的目标色就不必多取：重排无从下手，多请求只会浪费额度
        pool = min(MAX_PER_PAGE, per_tag * self._oversample) if targets else per_tag
        photos = self._collect(variants, pool)
        if not photos:
            return []

        if not targets:
            return [
                self._to_result(photo, query, _similarity(index, query.rank))
                for index, photo in enumerate(photos[:per_tag])
            ]

        inspected = [
            (photo, self._inspect(photo)) for photo in photos[: self._rerank_max]
        ]
        scored = score_candidates(inspected, targets)
        return [
            self._to_result(photo, query, score) for photo, score in scored[:per_tag]
        ]

    def _collect(self, variants: list[str], pool: int) -> list[UnsplashPhoto]:
        """按变体依次检索，按原图地址去重（保持「具体变体」的结果在前）。"""
        seen: set[str] = set()
        photos: list[UnsplashPhoto] = []
        for text in variants:
            for photo in self._client.search(text, pool):
                if photo.image_url in seen:
                    continue
                seen.add(photo.image_url)
                photos.append(photo)
        return photos

    def _inspect(
        self, photo: UnsplashPhoto
    ) -> list[tuple[tuple[float, float, float], float]] | None:
        """下载缩略图并提取主色；任何失败都返回 None（视为无颜色信息，绝不因此丢结果）。"""
        if not photo.thumb_url:
            return None
        try:
            data, _ = self._client.download(photo.thumb_url, max_bytes=THUMB_MAX_BYTES)
        except ProviderError:
            return None
        return dominant_lab_colors(data, k=THUMB_COLOR_COUNT) or None

    def _to_result(
        self, photo: UnsplashPhoto, query: MaterialQuery, similarity: float
    ) -> MaterialImageResult:
        return MaterialImageResult(
            label=query.material,
            similarity=similarity,
            content_type="image/jpeg",
            external_url=photo.image_url,
            source_url=photo.page_url,
            rank=0,  # 由 search() 统一编号
        )

"""能力层契约（abilities）。

四个能力的统一签名（与设计方案一致）：

  searchClothingImages      :: [网站列表]        -> [服装图片列表]
  identifyClothingMaterial  :: 服装图片            -> [材质 tag 列表]
  searchMaterialImages      :: [材质 tag 列表]     -> [材质图片列表]
  generateDesignImage       :: ([材质图], 设计想法) -> [设计图]

实现为真实 API；测试可用 fake 实现替换；两者签名一致、可热插拔。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# 内部 DTO（与 DB 模型解耦）
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class ClothingImageResult:
    """一张搜索到的服装图。

    `image_bytes` 有值表示需要落盘；否则使用 `external_url`（外部已托管地址）。
    """

    provider: str = ""
    content_type: str = "image/png"
    image_bytes: bytes | None = None
    external_url: str = ""
    page_url: str = ""
    title: str = ""
    site: str = ""
    source_query: str = ""


@dataclass(slots=True)
class MaterialTagResult:
    material: str
    material_en: str = ""
    confidence: float = 0.0
    evidence: str = ""
    category: str = ""
    rank: int = 0


@dataclass(slots=True)
class MaterialImageResult:
    tag: str
    similarity: float = 0.0
    content_type: str = "image/png"
    image_bytes: bytes | None = None
    external_url: str = ""
    source_url: str = ""
    rank: int = 0


@dataclass(slots=True)
class DesignImageResult:
    content_type: str = "image/png"
    image_bytes: bytes | None = None
    external_url: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    seed: int = 0
    rank: int = 0


@dataclass(slots=True)
class ReferenceImage:
    """设计参考图（原服装图），用于图生图时保留版型。"""

    image_bytes: bytes | None = None
    external_url: str = ""
    content_type: str = "image/png"
    caption: str = ""


# --------------------------------------------------------------------------- #
# 能力协议
# --------------------------------------------------------------------------- #
@runtime_checkable
class ClothingSearchProvider(Protocol):
    name: str

    def search(
        self, sites: list[str], query: str, count: int
    ) -> list[ClothingImageResult]:
        """searchClothingImages：从指定网站列表搜索服装图。"""
        ...


@runtime_checkable
class MaterialIdentifier(Protocol):
    name: str

    def identify(
        self,
        image_bytes: bytes | None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> list[MaterialTagResult]:
        """identifyClothingMaterial：识别服装材质，输出 tag + 可能度分析。"""
        ...


@runtime_checkable
class MaterialImageSearchProvider(Protocol):
    name: str

    def search(
        self, tags: list[MaterialTagResult], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        """searchMaterialImages：按材质 tag 检索面料特写图。"""
        ...


@runtime_checkable
class DesignImageGenerator(Protocol):
    name: str

    def generate(
        self,
        material_images: list[MaterialImageResult],
        design_idea: str,
        reference: ReferenceImage | None = None,
        num_candidates: int = 3,
    ) -> list[DesignImageResult]:
        """generateDesignImage：材质图 + 设计想法 → 设计图。"""
        ...


@dataclass
class Abilities:
    """一次性拿到全部能力实现。"""

    clothing_search: ClothingSearchProvider
    material_identifier: MaterialIdentifier
    material_search: MaterialImageSearchProvider
    design_generator: DesignImageGenerator
    providers: dict[str, str] = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    def summary(self) -> str:
        if not self.providers:
            return "<无>"
        return ", ".join(
            f"{name}={value or '<未配置>'}"
            for name, value in sorted(self.providers.items())
        )

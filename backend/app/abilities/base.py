"""能力层契约（abilities）。

四个能力的统一签名（与设计方案 / MVP 计划一致）：

  searchClothingImages      :: [网站列表]        -> [服装图片列表]
  identifyClothingMaterial  :: 服装图片           -> 材质卡片
  searchMaterialImages      :: [检索条件]          -> [面料参考图列表]
  generateDesignImage       :: ([面料图], 设计想法) -> [设计图]

实现为真实 API；测试可用 fake 实现替换；两者签名一致、可热插拔。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


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
class MaterialQuery:
    """材质图检索锚：由材质卡片编译出的检索条件。

    `material` 是受控词表里的材质名（如「棉」「桑蚕丝」），是检索的主锚；
    颜色 / 图案 / 光泽是可选增强项，用于让 query 更贴近「这种样子的面料特写」。
    """

    material: str
    material_en: str = ""
    color: str = ""
    pattern: str = ""
    gloss: str = ""
    rank: int = 0
    #: 主导色 hex（`#RRGGBB`）：既用于把颜色变成英文检索词，也作重排的兜底目标色
    color_hex: str = ""
    #: 卡片色板 `[{"hex": "#RRGGBB", "ratio": 0.72}, ...]`：候选图颜色重排的目标色
    palette: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ColorInfo:
    """A 层 · 颜色。"""

    dominant_hex: str = ""
    dominant_name: str = ""
    #: 主色 LAB（L, a, b）；模型未给出时为 None
    lab: tuple[float, float, float] | None = None
    #: [{"hex": "#RRGGBB", "ratio": 0.72}, ...]，ratio 之和归一化到 1
    palette: list[dict[str, Any]] = field(default_factory=list)
    #: 分布方式，如「整体均匀」
    distribution: str = ""


@dataclass(slots=True)
class PatternInfo:
    """A 层 · 图案。"""

    #: 纯色 / 条纹 / 格纹 / 碎花 / 定位印花
    type: str = ""
    scale: str = ""
    direction: str = ""
    layout: str = ""


@dataclass(slots=True)
class OpticalInfo:
    """A 层 · 光学属性。"""

    #: 哑光 / 微光 / 缎面 / 金属光
    gloss: str = ""
    transparency: str = ""


@dataclass(slots=True)
class FabricInfo:
    """B 层（面料 / 织法）。

    MVP 期只填材质名与受控词表回填的 `category`，`finish` 留空；
    材质名是材质图检索的锚点（见 `MaterialQuery`）。
    """

    material: str = ""
    material_en: str = ""
    category: str = ""
    finish: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class BehaviorInfo:
    """C 层（物理行为）。MVP 期填默认值，`is_default=True` 表示未经模型推断。"""

    weight: str = ""
    drape: str = ""
    confidence: float = 0.0
    is_default: bool = True


@dataclass(slots=True)
class RegionConfidence:
    """逐字段置信度：低置信字段在 UI 标灰，引导用户人工确认。"""

    color: float = 0.0
    pattern: float = 0.0
    gloss: float = 0.0


@dataclass(slots=True)
class MaterialRegionResult:
    """一个材质区域。

    MVP 期只有 `body` / 身片（区域分割模型尚未接入）；保留 region_id / region_type
    是为了后续接分割模型时不必再改 Schema。
    """

    region_id: str = "body"
    region_type: str = "身片"
    color: ColorInfo = field(default_factory=ColorInfo)
    pattern: PatternInfo = field(default_factory=PatternInfo)
    optical: OpticalInfo = field(default_factory=OpticalInfo)
    fabric: FabricInfo = field(default_factory=FabricInfo)
    behavior: BehaviorInfo = field(default_factory=BehaviorInfo)
    confidence: RegionConfidence = field(default_factory=RegionConfidence)
    #: 材质小样（干净面料 patch）字节；ability 层只裁，落盘由编排器负责
    swatch_bytes: bytes | None = None
    #: 小样的归一化裁剪框 (left, top, right, bottom)，取值 0~1
    swatch_crop_box: tuple[float, float, float, float] | None = None
    swatch_content_type: str = "image/png"


@dataclass(slots=True)
class MaterialCardResult:
    """材质卡片：连接「识别」与「生成」的最小充分中间层（MVP 计划 §3）。"""

    #: 品类：MVP 只支持 女装上衣 / 连衣裙
    category: str = ""
    regions: list[MaterialRegionResult] = field(default_factory=list)
    #: 整体判断依据（视觉依据汇总）
    evidence: str = ""
    #: 用户自由文本补充（识别时为空，编辑时由用户填写，编译进生图提示词）
    note: str = ""
    schema_version: str = "1.0"
    #: 纹理指纹（embedding）引用；MVP 期留空占位
    texture_embedding_ref: str = ""
    overall_confidence: float = 0.0

    @property
    def primary(self) -> MaterialRegionResult | None:
        """主区域（MVP 期即唯一区域）。"""
        return self.regions[0] if self.regions else None


@dataclass(slots=True)
class MaterialImageResult:
    """一张面料参考图（按卡片检索得到，或用户在任务详情页上传）。

    `label` 是展示与提示词用的标签：检索结果 = 材质名，上传 = 「上传的面料图」。
    """

    label: str
    similarity: float = 0.0
    content_type: str = "image/png"
    image_bytes: bytes | None = None
    external_url: str = ""
    source_url: str = ""
    rank: int = 0
    #: search = 按卡片检索得到；upload = 用户上传
    origin: str = "search"


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
    #: 该候选是否**真的**把原服装图送进了模型（由 provider 依据实际送出的参考图填写，
    #: 而不是照抄任务开关：无字节/超参考图上限时原图会被丢弃）
    used_reference: bool = False


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
    ) -> MaterialCardResult:
        """identifyClothingMaterial：识别服装材质，输出「材质卡片」。

        卡片含逐区域的视觉属性（颜色 / 图案 / 光泽）、B/C 层占位字段、
        逐字段置信度，以及材质小样（swatch）字节。见 MVP 计划 §3.1。
        """
        ...


@runtime_checkable
class MaterialImageSearchProvider(Protocol):
    name: str

    def search(
        self, queries: list[MaterialQuery], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        """searchMaterialImages：按检索锚（材质名 + 颜色/图案/光泽）检索面料特写图。"""
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
        material_summary: str = "",
    ) -> list[DesignImageResult]:
        """generateDesignImage：材质图 + 设计想法 → 设计图。

        `material_summary` 是材质卡片编译出的文字要求（颜色 / 图案 / 光泽 / 面料 /
        用户备注），拼进提示词；为空时实现应回退到「只用材质图标签」的旧行为。
        """
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

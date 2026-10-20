"""API 契约（Pydantic）。前端 `src/lib/types.ts` 与此保持一致。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# 输出模型
# --------------------------------------------------------------------------- #
class ClothingImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_url: str
    thumbnail_url: str
    page_url: str
    title: str
    site: str
    source_query: str
    provider: str


class MaterialImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    #: 展示 / 提示词用标签：检索结果 = 材质名，上传 = 「上传的面料图」
    label: str
    image_url: str
    thumbnail_url: str
    source_url: str
    similarity: float
    selected: bool
    rank: int
    #: search = 按卡片检索；upload = 用户上传
    origin: str = "search"


# --------------------------------------------------------------------------- #
# 材质卡片（MVP 计划 §3.1）
# --------------------------------------------------------------------------- #
class ColorOut(BaseModel):
    """A 层 · 颜色。"""

    dominant_hex: str = ""
    dominant_name: str = ""
    lab: list[float] | None = None
    #: [{"hex": "#RRGGBB", "ratio": 0.72}, ...]，ratio 之和为 1
    palette: list[dict] = Field(default_factory=list)
    distribution: str = ""


class PatternOut(BaseModel):
    """A 层 · 图案。"""

    type: str = ""
    scale: str = ""
    direction: str = ""
    layout: str = ""


class OpticalOut(BaseModel):
    """A 层 · 光学属性。"""

    gloss: str = ""
    transparency: str = ""


class FabricOut(BaseModel):
    """B 层（面料 / 织法）。MVP 期只有 material / material_en / category 有值。"""

    material: str = ""
    material_en: str = ""
    category: str = ""
    finish: str = ""
    confidence: float = 0.0


class BehaviorOut(BaseModel):
    """C 层（物理行为）。MVP 期填默认值；`is_default=True` 表示未经模型推断。"""

    weight: str = ""
    drape: str = ""
    confidence: float = 0.0
    is_default: bool = True


class RegionConfidenceOut(BaseModel):
    """逐字段置信度：低置信字段在 UI 标灰，引导用户确认。"""

    color: float = 0.0
    pattern: float = 0.0
    gloss: float = 0.0


class SwatchOut(BaseModel):
    """材质小样（干净面料 patch）：生成阶段的保真锚点。"""

    url: str = ""
    thumbnail_url: str = ""
    crop_box: list[float] | None = None
    texture_embedding_ref: str = ""


class MaterialRegionOut(BaseModel):
    region_id: str
    region_type: str
    color: ColorOut
    pattern: PatternOut
    optical: OpticalOut
    fabric: FabricOut
    behavior: BehaviorOut
    confidence: RegionConfidenceOut


class MaterialCardOut(BaseModel):
    """识别 + 人工确认后的材质卡片。

    MVP 期只有身片一个区域，小样挂在卡片上（多区域时再下沉到 region）。
    """

    id: str
    task_id: str
    #: ai = 模型识别结果；user = 用户改过的卡片
    source: str
    category: str
    regions: list[MaterialRegionOut] = Field(default_factory=list)
    evidence: str = ""
    note: str = ""
    schema_version: str = "1.0"
    overall_confidence: float = 0.0
    swatch: SwatchOut = Field(default_factory=SwatchOut)
    updated_at: datetime


class DesignImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_url: str
    thumbnail_url: str
    prompt: str
    model: str
    seed: int
    rank: int
    #: 该候选是否真的把原服装图作为参考图送进了模型
    used_reference: bool = False


class TaskEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage: str
    status: str
    message: str
    progress: float
    created_at: datetime


class TaskSummary(BaseModel):
    id: str
    status: str
    error: str | None = None
    design_idea: str = ""
    auto_generate: bool = False
    require_material_selection: bool = False
    #: 生成设计图时是否参考原服装图（True = 保留版型）
    use_reference: bool = True
    clothing_image: ClothingImageOut
    #: 是否已识别出材质卡片
    has_material_card: bool = False
    material_image_count: int = 0
    design_image_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskDetail(TaskSummary):
    material_card: MaterialCardOut | None = None
    material_images: list[MaterialImageOut] = Field(default_factory=list)
    design_images: list[DesignImageOut] = Field(default_factory=list)
    events: list[TaskEventOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class SearchClothingRequest(BaseModel):
    sites: list[str] = Field(default_factory=list)
    query: str = ""
    count: int = Field(default=24, ge=1, le=60)


class SearchClothingResponse(BaseModel):
    images: list[ClothingImageOut]
    warnings: list[str] = Field(default_factory=list)


class CreateTasksRequest(BaseModel):
    clothing_image_ids: list[str] = Field(min_length=1)
    design_idea: str = ""
    auto_generate: bool = False
    require_material_selection: bool = False


class CreateTasksResponse(BaseModel):
    tasks: list[TaskSummary]


class BulkDeleteTasksRequest(BaseModel):
    """批量删除：按 id 列表（去重后删除，不存在的 id 不算失败）。"""

    task_ids: list[str] = Field(min_length=1, max_length=500)


class BulkDeleteTasksResponse(BaseModel):
    deleted: int
    not_found: list[str] = Field(default_factory=list)


class ColorUpdate(BaseModel):
    dominant_hex: str | None = None
    dominant_name: str | None = None
    palette: list[dict] | None = None
    distribution: str | None = None


class PatternUpdate(BaseModel):
    type: str | None = None
    scale: str | None = None
    direction: str | None = None
    layout: str | None = None


class OpticalUpdate(BaseModel):
    gloss: str | None = None
    transparency: str | None = None


class FabricUpdate(BaseModel):
    material: str | None = None
    material_en: str | None = None
    category: str | None = None
    finish: str | None = None


class BehaviorUpdate(BaseModel):
    weight: str | None = None
    drape: str | None = None


class RegionUpdate(BaseModel):
    """区域局部更新：`None` = 不修改该字段（部分更新语义）。"""

    color: ColorUpdate | None = None
    pattern: PatternUpdate | None = None
    optical: OpticalUpdate | None = None
    fabric: FabricUpdate | None = None
    behavior: BehaviorUpdate | None = None


class MaterialCardUpdateRequest(BaseModel):
    """材质卡片局部更新（编辑入口 1「改属性」与 3「写文字」）。

    值传 `null` = 不修改；`region` 只作用于 MVP 的主区域（身片）。
    入口 2「换小样」（上传面料图）走 `POST /api/tasks/{id}/material-images`。
    """

    category: str | None = None
    note: str | None = None
    evidence: str | None = None
    region: RegionUpdate | None = None


class CardOptionsOut(BaseModel):
    """材质卡片的受控取值（供前端渲染下拉框，避免前端与后端枚举漂移）。"""

    category: list[str] = Field(default_factory=list)
    pattern_type: list[str] = Field(default_factory=list)
    gloss: list[str] = Field(default_factory=list)
    transparency: list[str] = Field(default_factory=list)
    weight: list[str] = Field(default_factory=list)
    drape: list[str] = Field(default_factory=list)
    material: list[str] = Field(default_factory=list)


class SelectMaterialsRequest(BaseModel):
    """material_image_ids 为空表示「每个 tag 取相似度最高的若干张」。"""

    material_image_ids: list[str] | None = None


class GenerateRequest(BaseModel):
    design_idea: str = ""
    num_candidates: int = Field(default=3, ge=1, le=6)
    #: 是否把原服装图作为参考图；None = 保持任务上的已有设置（部分更新语义）
    use_reference: bool | None = None


class MaterialTagDef(BaseModel):
    """材质词表中的一条定义。"""

    material: str
    material_en: str
    category: str
    gloss: str
    drape: str
    keywords: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 登录 / 许可（entitlement-api-new）
# --------------------------------------------------------------------------- #
class RequestLoginRequest(BaseModel):
    #: 只做长度约束；格式由 entitlement-api 校验（避免额外引入 email-validator）
    email: str = Field(min_length=3, max_length=254)


class RequestLoginResponse(BaseModel):
    email: str
    expires_at: datetime


class VerifyLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=6, max_length=6)


class AuthStatusOut(BaseModel):
    """当前登录状态与许可证概要（只读，不含任何令牌）。"""

    authenticated: bool = True
    email: str
    product: str
    edition: str
    expires_at: datetime


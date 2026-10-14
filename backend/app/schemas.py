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


class MaterialTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    material: str
    material_en: str
    confidence: float
    evidence: str
    category: str
    source: str
    rank: int


class MaterialImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tag: str
    image_url: str
    thumbnail_url: str
    source_url: str
    similarity: float
    selected: bool
    rank: int


class DesignImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    image_url: str
    thumbnail_url: str
    prompt: str
    model: str
    seed: int
    rank: int


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
    clothing_image: ClothingImageOut
    tag_count: int = 0
    material_image_count: int = 0
    design_image_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskDetail(TaskSummary):
    material_tags: list[MaterialTagOut] = Field(default_factory=list)
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


class MaterialTagInput(BaseModel):
    material: str
    material_en: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str = ""
    category: str = ""


class ConfirmMaterialsRequest(BaseModel):
    tags: list[MaterialTagInput] = Field(min_length=1)


class SelectMaterialsRequest(BaseModel):
    """material_image_ids 为空表示「每个 tag 取相似度最高的若干张」。"""

    material_image_ids: list[str] | None = None


class GenerateRequest(BaseModel):
    design_idea: str = ""
    num_candidates: int = Field(default=3, ge=1, le=6)


class MaterialTagDef(BaseModel):
    """材质词表中的一条定义。"""

    material: str
    material_en: str
    category: str
    gloss: str
    drape: str
    keywords: list[str] = Field(default_factory=list)

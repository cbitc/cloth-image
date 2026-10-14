"""真实材质图检索 —— 占位实现。

MVP：复用服装图搜索适配器，query 换成 `"{材质} fabric texture close-up"`。
生产：自建面料图库 + CLIP/SigLIP embedding + 向量库（pgvector / Qdrant），
      用材质 tag 文本 embedding 做文搜图（见设计方案 §2.3）。
"""

from __future__ import annotations

from app.abilities.base import MaterialImageResult, MaterialTagResult
from app.abilities.prompting import build_material_query


class SerpApiMaterialSearchProvider:
    name = "serpapi"

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    def search(
        self, tags: list[MaterialTagResult], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        # TODO: 对每个 tag 用 build_material_query(tag.material) 调图库搜索，
        #       返回 external_url；编排器会镜像到对象存储。
        raise NotImplementedError(
            "SerpApiMaterialSearchProvider 尚未实现，请设置 PROVIDER_MODE=mock 或补全实现。"
        )


def describe_query(tag: MaterialTagResult) -> str:
    return build_material_query(tag.material)

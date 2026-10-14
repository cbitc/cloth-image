"""材质词表加载与查询。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent / "materials.yaml"


@lru_cache
def load_taxonomy() -> list[dict]:
    with TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return list(data)


@lru_cache
def _by_material() -> dict[str, dict]:
    return {item["material"]: item for item in load_taxonomy()}


def get_definition(material: str) -> dict | None:
    return _by_material().get(material)


def all_materials() -> list[str]:
    return [item["material"] for item in load_taxonomy()]


def material_names() -> str:
    """用于注入 prompt 的标签清单文本。"""
    return "、".join(all_materials())


def build_material_query(material: str) -> str:
    """把材质 tag 转成「面料特写」检索词。"""
    definition = get_definition(material)
    if definition and definition.get("keywords"):
        return definition["keywords"][0]
    return f"{material} fabric texture close-up"


def build_material_query_zh(material: str) -> str:
    definition = get_definition(material)
    if definition and len(definition.get("keywords", [])) > 1:
        return definition["keywords"][1]
    return f"{material} 面料 纹理 特写"


__all__ = [
    "load_taxonomy",
    "get_definition",
    "all_materials",
    "material_names",
    "build_material_query",
    "build_material_query_zh",
]

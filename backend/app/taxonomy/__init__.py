"""材质词表加载与查询。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent / "materials.yaml"

# --------------------------------------------------------------------------- #
# 材质卡片的受控取值（与前端 `lib/types.ts` / `MaterialCardEditor` 保持一致）
# --------------------------------------------------------------------------- #
#: 图案五大类（MVP 计划 §2.1）
PATTERN_TYPES: tuple[str, ...] = ("纯色", "条纹", "格纹", "碎花", "定位印花")
#: 光泽四档
GLOSS_LEVELS: tuple[str, ...] = ("哑光", "微光", "缎面", "金属光")
TRANSPARENCY_LEVELS: tuple[str, ...] = ("不透明", "半透明", "透明")
#: C 层（物理行为）占位值，MVP 期不做推断、填默认
WEIGHT_LEVELS: tuple[str, ...] = ("轻薄", "中等", "厚重")
DRAPE_LEVELS: tuple[str, ...] = ("挺括", "适中", "垂坠")
#: 品类：首期限定女装上衣 + 连衣裙
CATEGORY_OPTIONS: tuple[str, ...] = ("女装上衣", "连衣裙")

DEFAULT_PATTERN_TYPE = PATTERN_TYPES[0]
DEFAULT_GLOSS = GLOSS_LEVELS[0]
DEFAULT_TRANSPARENCY = TRANSPARENCY_LEVELS[0]
DEFAULT_WEIGHT = "中等"
DEFAULT_DRAPE = "适中"
DEFAULT_CATEGORY = CATEGORY_OPTIONS[0]


def card_options() -> dict[str, list[str]]:
    """供前端渲染下拉框的受控取值。"""
    return {
        "category": list(CATEGORY_OPTIONS),
        "pattern_type": list(PATTERN_TYPES),
        "gloss": list(GLOSS_LEVELS),
        "transparency": list(TRANSPARENCY_LEVELS),
        "weight": list(WEIGHT_LEVELS),
        "drape": list(DRAPE_LEVELS),
        "material": all_materials(),
    }


@lru_cache
def load_taxonomy() -> list[dict]:
    with TAXONOMY_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return list(data)


@lru_cache
def _by_material() -> dict[str, dict]:
    return {item["material"]: item for item in load_taxonomy()}


@lru_cache
def _by_material_en() -> dict[str, dict]:
    return {
        str(item.get("material_en", "")).strip().lower(): item
        for item in load_taxonomy()
        if item.get("material_en")
    }


def _compact(text: str) -> str:
    return re.sub(r"[\s\-_/]+", "", text.strip().lower())


def match_material(name: str, material_en: str | None = None) -> dict | None:
    """把模型输出的材质名归一化回受控词表条目（中英文 / 分隔符变体都能对）。

    找不到时返回 None —— 调用方决定是原样保留还是回退默认值。
    """
    name = (name or "").strip()
    if name in _by_material():
        return _by_material()[name]

    for candidate in (name, material_en or ""):
        key = candidate.strip().lower()
        if key and key in _by_material_en():
            return _by_material_en()[key]

    compact = _compact(name)
    if compact:
        for english, definition in _by_material_en().items():
            if _compact(english) == compact:
                return definition
    return None


def get_definition(material: str) -> dict | None:
    return _by_material().get(material)


def all_materials() -> list[str]:
    return [item["material"] for item in load_taxonomy()]


def material_names() -> str:
    """用于注入 prompt 的标签清单文本。"""
    return "、".join(all_materials())


def material_labels() -> str:
    """用于注入 prompt 的「中文名(英文名)」清单。"""
    return "、".join(
        f"{item['material']}({item.get('material_en', '')})" for item in load_taxonomy()
    )


def build_material_query(material: str) -> str:
    """把面料名转成「面料特写」检索词。"""
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
    "material_labels",
    "match_material",
    "card_options",
    "build_material_query",
    "build_material_query_zh",
    "PATTERN_TYPES",
    "GLOSS_LEVELS",
    "TRANSPARENCY_LEVELS",
    "WEIGHT_LEVELS",
    "DRAPE_LEVELS",
    "CATEGORY_OPTIONS",
    "DEFAULT_PATTERN_TYPE",
    "DEFAULT_GLOSS",
    "DEFAULT_TRANSPARENCY",
    "DEFAULT_WEIGHT",
    "DEFAULT_DRAPE",
    "DEFAULT_CATEGORY",
]

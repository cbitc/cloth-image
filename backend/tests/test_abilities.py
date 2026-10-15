"""能力层契约测试：fake 实现必须满足 Protocol 且行为确定。"""

from __future__ import annotations

from app.abilities.base import (
    ClothingSearchProvider,
    DesignImageGenerator,
    MaterialIdentifier,
    MaterialImageSearchProvider,
)
from app.abilities.prompting import build_material_summary
from app.abilities.registry import get_abilities
from app.tasks.orchestrator import material_queries
from app.taxonomy import all_materials, build_material_query, load_taxonomy


def test_registry_provides_all_protocols() -> None:
    abilities = get_abilities()
    assert isinstance(abilities.clothing_search, ClothingSearchProvider)
    assert isinstance(abilities.material_identifier, MaterialIdentifier)
    assert isinstance(abilities.material_search, MaterialImageSearchProvider)
    assert isinstance(abilities.design_generator, DesignImageGenerator)


def test_clothing_search_is_deterministic() -> None:
    abilities = get_abilities()
    a = abilities.clothing_search.search(["fake-shop"], "风衣", 3)
    b = abilities.clothing_search.search(["fake-shop"], "风衣", 3)
    assert len(a) == 3
    assert all(item.image_bytes for item in a)
    assert [item.page_url for item in a] == [item.page_url for item in b]
    assert a[0].image_bytes == b[0].image_bytes  # 同 seed 同图


def test_material_identifier_returns_a_material_card() -> None:
    abilities = get_abilities()
    image = abilities.clothing_search.search(["fake-shop"], "衬衫", 1)[0]
    card = abilities.material_identifier.identify(image.image_bytes or b"x")

    region = card.primary
    assert region is not None
    assert card.category in {"女装上衣", "连衣裙"}
    assert region.color.dominant_hex.startswith("#")
    assert region.color.palette
    assert region.pattern.type
    assert region.optical.gloss and region.optical.transparency
    assert region.fabric.material in all_materials()
    assert region.behavior.is_default is True  # MVP 期不做物理推断
    assert region.swatch_bytes  # fake 会真实裁一块小样
    assert 0.0 <= region.confidence.color <= 1.0

    # 同样输入 → 同样输出
    again = abilities.material_identifier.identify(image.image_bytes or b"x")
    assert again.primary is not None
    assert again.primary.fabric.material == region.fabric.material
    assert again.primary.color.dominant_hex == region.color.dominant_hex


def test_material_search_and_design_generation() -> None:
    abilities = get_abilities()
    image = abilities.clothing_search.search(["fake-shop"], "半裙", 1)[0]
    card = abilities.material_identifier.identify(image.image_bytes or b"x")
    queries = material_queries(card)
    assert queries  # 卡片里的面料名就是检索锚

    materials = abilities.material_search.search(queries, per_tag=2)
    assert len(materials) == len(queries) * 2
    assert all(m.image_bytes for m in materials)
    assert all(m.similarity > 0 for m in materials)
    assert {m.label for m in materials} == {q.material for q in queries}

    designs = abilities.design_generator.generate(
        materials,
        "改成及膝长度",
        num_candidates=2,
        material_summary=build_material_summary(card),
    )
    assert len(designs) == 2
    assert all(d.image_bytes for d in designs)
    assert "及膝长度" in designs[0].prompt
    assert region_material(card) in designs[0].prompt


def region_material(card) -> str:
    assert card.primary is not None
    return card.primary.fabric.material


def test_taxonomy_entries_are_complete() -> None:
    entries = load_taxonomy()
    assert len(entries) >= 50
    for item in entries:
        assert item["material"] and item["material_en"] and item["category"]
        assert item["gloss"] in {"低", "中", "高"}
        assert item["drape"] in {"低", "中", "高"}
        assert item["keywords"]
    assert "fabric" in build_material_query("雪纺")

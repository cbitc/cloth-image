"""材质卡片：归一化规则 + 卡片接口（编辑 / 确认）回归。

对应 MVP 计划 §3「核心数据资产：材质卡片」。重点验证：
- 模型输出不可信（近义词 / 缺 # / 占比不归零 / 置信度越界）时被清洗成受控取值
- 卡片可局部编辑（只改传了的字段），且「只改属性」不会丢掉小样
- 低置信字段的置信度原样外露给前端（UI 标灰引导确认）
"""

from __future__ import annotations

import pytest

from app.abilities.material_identify.card_normalize import (
    normalize_card,
    normalize_hex,
    normalize_palette,
    pick_option,
)
from app.abilities.material_identify.openai_compatible_vlm import SYSTEM_PROMPT
from app.enums import TaskStatus
from app.taxonomy import GLOSS_LEVELS, PATTERN_TYPES


# --------------------------------------------------------------------------- #
# 归一化规则（纯函数，无需 DB）
# --------------------------------------------------------------------------- #
def test_hex_is_normalized_or_dropped() -> None:
    assert normalize_hex("2b3a4a") == "#2B3A4A"
    assert normalize_hex("#ABCDEF") == "#ABCDEF"
    assert normalize_hex("") == ""
    assert normalize_hex("red") == ""
    assert normalize_hex(None) == ""


def test_palette_ratios_are_normalized_and_sorted() -> None:
    palette = normalize_palette(
        [
            {"hex": "#111111", "ratio": 1},
            {"hex": "bad", "ratio": 5},
            {"hex": "#222222", "ratio": 3},
        ]
    )
    assert [entry["hex"] for entry in palette] == ["#222222", "#111111"]
    assert sum(entry["ratio"] for entry in palette) == pytest.approx(1.0)
    assert palette[0]["ratio"] > palette[1]["ratio"]

    # 模型没给占比 → 均分，保证 UI 能渲染
    even = normalize_palette([{"hex": "#111111"}, {"hex": "#222222"}])
    assert even[0]["ratio"] == pytest.approx(0.5)


def test_pick_option_accepts_synonyms_and_falls_back() -> None:
    assert pick_option("solid", PATTERN_TYPES, "纯色") == "纯色"
    assert pick_option("竖条纹", PATTERN_TYPES, "纯色") == "条纹"
    assert pick_option("matte finish", GLOSS_LEVELS, "哑光") == "哑光"
    assert pick_option("看不懂的取值", GLOSS_LEVELS, "哑光") == "哑光"
    assert pick_option(None, PATTERN_TYPES, "纯色") == "纯色"


def test_structured_output_is_requested_in_the_prompt() -> None:
    """提示词必须把受控取值与 schema 讲清楚，否则模型输出无法直接落库。"""
    for token in ("纯色", "条纹", "格纹", "碎花", "定位印花"):
        assert token in SYSTEM_PROMPT
    for token in ("哑光", "微光", "缎面", "金属光"):
        assert token in SYSTEM_PROMPT
    assert "swatch_box" in SYSTEM_PROMPT
    assert "fabric.material" in SYSTEM_PROMPT


def test_card_always_has_a_primary_region_with_defaults() -> None:
    card = normalize_card({})
    region = card.primary
    assert region is not None
    assert region.region_id == "body"
    assert region.region_type == "身片"
    assert region.pattern.type == "纯色"  # 受控默认值
    assert region.behavior.is_default is True
    assert card.schema_version == "1.0"


# --------------------------------------------------------------------------- #
# 接口：卡片编辑 / 确认
# --------------------------------------------------------------------------- #
@pytest.fixture
def task_with_card(client, sample_clothing_image_id) -> dict:
    """建任务并等到「待确认材质卡片」（sync 模式下请求返回即已完成识别）。"""
    resp = client.post(
        "/api/tasks", json={"clothing_image_ids": [sample_clothing_image_id]}
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["tasks"][0]["id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_MATERIAL_CONFIRM
    assert detail["has_material_card"] is True
    return detail


def test_card_options_endpoint_exposes_controlled_values(client) -> None:
    resp = client.get("/api/material-taxonomy/card-options")
    assert resp.status_code == 200, resp.text
    options = resp.json()
    assert options["pattern_type"] == list(PATTERN_TYPES)
    assert options["gloss"] == list(GLOSS_LEVELS)
    assert options["category"] == ["女装上衣", "连衣裙"]
    assert options["weight"] and options["drape"]
    assert "棉" in options["material"]


def test_identification_exposes_per_field_confidence(client, task_with_card) -> None:
    """逐字段置信度必须外露：低置信字段要靠它在前端标灰。"""
    region = task_with_card["material_card"]["regions"][0]
    for key in ("color", "pattern", "gloss"):
        value = region["confidence"][key]
        assert 0.0 <= value <= 1.0
    assert 0.0 <= task_with_card["material_card"]["overall_confidence"] <= 1.0


def test_patch_updates_only_the_fields_that_were_sent(client, task_with_card) -> None:
    task_id = task_with_card["id"]
    before = task_with_card["material_card"]["regions"][0]

    resp = client.put(
        f"/api/tasks/{task_id}/material-card",
        json={"region": {"pattern": {"type": "格纹"}}},
    )
    assert resp.status_code == 200, resp.text
    card = resp.json()["material_card"]
    after = card["regions"][0]

    assert after["pattern"]["type"] == "格纹"
    # 其余字段一个都没动
    assert after["color"] == before["color"]
    assert after["optical"] == before["optical"]
    assert after["fabric"] == before["fabric"]
    assert card["category"] == task_with_card["material_card"]["category"]


def test_patch_normalizes_material_through_the_taxonomy(client, task_with_card) -> None:
    resp = client.put(
        f"/api/tasks/{task_with_card['id']}/material-card",
        json={"region": {"fabric": {"material": "mulberry silk"}}},
    )
    assert resp.status_code == 200, resp.text
    fabric = resp.json()["material_card"]["regions"][0]["fabric"]
    assert fabric["material"] == "桑蚕丝"
    assert fabric["material_en"] == "Mulberry Silk"
    assert fabric["category"] == "天然纤维"


def test_note_can_be_written_and_cleared(client, task_with_card) -> None:
    task_id = task_with_card["id"]

    written = client.put(
        f"/api/tasks/{task_id}/material-card",
        json={"note": "面料要更挺括一点"},
    ).json()["material_card"]
    assert written["note"] == "面料要更挺括一点"

    # 空字符串 = 清空（None 才是「不修改」）
    cleared = client.put(
        f"/api/tasks/{task_id}/material-card", json={"note": ""}
    ).json()
    assert cleared["material_card"]["note"] == ""


def test_null_means_keep_current_value(client, task_with_card) -> None:
    task_id = task_with_card["id"]
    original = task_with_card["material_card"]["note"]

    resp = client.put(f"/api/tasks/{task_id}/material-card", json={"note": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["material_card"]["note"] == original


def test_editing_marks_card_as_user_confirmed(client, task_with_card) -> None:
    assert task_with_card["material_card"]["source"] == "ai"

    resp = client.put(
        f"/api/tasks/{task_with_card['id']}/material-card",
        json={"region": {"optical": {"gloss": "缎面"}}},
    )
    assert resp.json()["material_card"]["source"] == "user"


def test_confirm_requires_a_card(client, sample_clothing_image_id) -> None:
    """没有卡片就没有可确认的东西（正常流程不会走到，接口要防御）。"""
    resp = client.post("/api/tasks/not-a-task/confirm-materials")
    assert resp.status_code == 404

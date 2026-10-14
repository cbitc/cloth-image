"""能力配置接口与校验测试。"""

from __future__ import annotations

import pytest

from app import settings_store
from app.abilities.registry import reset_abilities_cache
from app.config import apply_overrides
from app.db.session import SessionLocal
from app.settings_spec import SettingsValidationError, coerce, validate_patch


@pytest.fixture(autouse=True)
def _restore_overrides():
    """用例前后都清空覆盖项，避免污染其它测试（覆盖项是模块级全局状态）。"""

    def clean() -> None:
        with SessionLocal() as db:
            settings_store.clear_all(db)
        apply_overrides({})
        reset_abilities_cache()

    clean()
    yield
    clean()


def _ability(body: dict, name: str) -> dict:
    return next(item for item in body["ability_status"] if item["ability"] == name)


# --------------------------------------------------------------------------- #
# 读取
# --------------------------------------------------------------------------- #
def test_get_returns_structured_config(client) -> None:
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()

    assert [group["name"] for group in body["groups"]][0] == "能力提供方"
    assert all("fields" in group and group["fields"] for group in body["groups"])

    # 非密钥字段给真值，密钥字段只给状态
    assert body["values"]["vlm_model"] == "qwen3-vl-plus"
    assert body["values"]["image_size"] == "1024x1024"
    assert body["secrets"]["maas_api_key"] == {"configured": False, "overridden": False}
    assert "value" not in body["secrets"]["maas_api_key"]

    assert len(body["ability_status"]) == 4
    assert body["abilities"] == {
        "clothing_search": "mock",
        "material_identifier": "mock",
        "material_search": "mock",
        "design_generator": "mock",
    }


def test_ability_status_flags_placeholder_implementations(client) -> None:
    body = client.get("/api/settings").json()

    # serpapi / fal 仍是占位实现，应明确标出来
    web = _ability(body, "clothing_search")
    assert set(web["options"]) == {"mock", "serpapi"}

    client.put(
        "/api/settings", json={"values": {"clothing_search_provider": "serpapi"}}
    )
    body = client.get("/api/settings").json()
    web = _ability(body, "clothing_search")
    assert web["provider"] == "serpapi"
    assert web["state"] == "stub"
    assert web["state_label"] == "占位实现"


def test_ability_status_flags_missing_key(client) -> None:
    client.put(
        "/api/settings", json={"values": {"material_identifier_provider": "maas"}}
    )
    body = client.get("/api/settings").json()

    identifier = _ability(body, "material_identifier")
    assert identifier["provider"] == "maas"
    assert identifier["state"] == "missing_key"
    assert any("MAAS_API_KEY" in warning for warning in body["warnings"])


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def test_override_beats_environment_variable(client) -> None:
    """conftest 里环境变量把 provider 固定为 mock；覆盖项应能压过它。"""
    before = client.get("/api/settings").json()
    assert before["abilities"]["material_identifier"] == "mock"

    resp = client.put(
        "/api/settings", json={"values": {"material_identifier_provider": "maas"}}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["abilities"]["material_identifier"] == "maas"
    assert body["mode"] == "mixed"
    assert body["overridden"] == ["material_identifier_provider"]


def test_updating_secret_reports_configured_without_echoing_value(client) -> None:
    resp = client.put(
        "/api/settings", json={"values": {"maas_api_key": "sk-secret-value"}}
    )
    assert resp.status_code == 200, resp.text

    secret = resp.json()["secrets"]["maas_api_key"]
    assert secret["configured"] is True
    assert secret["overridden"] is True
    assert "sk-secret-value" not in resp.text  # 绝不回传密钥

    # 视图里也不应出现
    assert "sk-secret-value" not in client.get("/api/settings").text


def test_null_value_removes_override_and_falls_back(client) -> None:
    client.put("/api/settings", json={"values": {"vlm_model": "my-custom-model"}})
    assert (
        client.get("/api/settings").json()["values"]["vlm_model"] == "my-custom-model"
    )

    resp = client.put("/api/settings", json={"values": {"vlm_model": None}})
    assert resp.status_code == 200

    body = resp.json()
    assert body["values"]["vlm_model"] == "qwen3-vl-plus"  # 回退到代码默认值
    assert "vlm_model" not in body["overridden"]


def test_delete_resets_everything(client) -> None:
    client.put(
        "/api/settings",
        json={
            "values": {
                "material_identifier_provider": "maas",
                "design_generator_provider": "dashscope",
            }
        },
    )

    resp = client.delete("/api/settings")
    assert resp.status_code == 200
    body = resp.json()

    assert body["removed"] == 2
    assert body["overridden"] == []
    assert body["abilities"]["material_identifier"] == "mock"


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def test_unknown_field_is_rejected(client) -> None:
    resp = client.put("/api/settings", json={"values": {"database_url": "sqlite:///x"}})
    assert resp.status_code == 400
    assert "不可配置" in resp.json()["detail"]


def test_invalid_choice_is_rejected(client) -> None:
    resp = client.put(
        "/api/settings", json={"values": {"design_generator_provider": "midjourney"}}
    )
    assert resp.status_code == 400
    assert "只能是" in resp.json()["detail"]


def test_image_size_format_is_validated(client) -> None:
    """实测 1024*1024 会被接口拒绝，所以这里就要拦住。"""
    resp = client.put("/api/settings", json={"values": {"image_size": "1024*1024"}})
    assert resp.status_code == 400
    assert "格式不符" in resp.json()["detail"]

    assert (
        client.put(
            "/api/settings", json={"values": {"image_size": "768x1024"}}
        ).status_code
        == 200
    )


def test_numeric_range_is_enforced(client) -> None:
    # 实测 qwen-image-3.0 最多接受 3 张参考图
    resp = client.put("/api/settings", json={"values": {"image_max_refs": 9}})
    assert resp.status_code == 400
    assert "不能大于 3" in resp.json()["detail"]

    assert (
        client.put(
            "/api/settings", json={"values": {"image_max_refs": "2"}}
        ).status_code
        == 200
    )
    assert client.get("/api/settings").json()["values"]["image_max_refs"] == 2


def test_empty_patch_is_rejected(client) -> None:
    resp = client.put("/api/settings", json={"values": {}})
    assert resp.status_code == 400
    assert "没有需要更新" in resp.json()["detail"]


def test_write_can_be_disabled_by_env(client, monkeypatch) -> None:
    """无鉴权的服务对外暴露时，可关掉写入能力只保留查看。"""
    from app import config

    disabled = config.Settings(settings_write_enabled=False)
    monkeypatch.setattr("app.api.settings.get_settings", lambda: disabled)

    resp = client.put("/api/settings", json={"values": {"vlm_model": "x"}})
    assert resp.status_code == 403
    assert "禁用" in resp.json()["detail"]

    # 读取不受影响
    assert client.get("/api/settings").status_code == 200


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
def test_coerce_handles_types() -> None:
    assert coerce("image_max_refs", "2") == 2
    assert coerce("provider_timeout_s", "12.5") == 12.5
    assert coerce("prompt_extend", "true") is True
    assert coerce("prompt_extend", 0) is False
    assert coerce("provider_mode", " mock ") == "mock"

    with pytest.raises(SettingsValidationError):
        coerce("image_max_refs", "abc")
    with pytest.raises(SettingsValidationError):
        coerce("prompt_extend", "maybe")
    with pytest.raises(SettingsValidationError):
        coerce("nope", "1")


def test_validate_patch_keeps_none_and_cleans_values() -> None:
    cleaned = validate_patch({"vlm_model": " m ", "image_max_refs": 2, "fal_key": None})
    assert cleaned == {"vlm_model": "m", "image_max_refs": 2, "fal_key": None}

"""把配置组装成给前端设置页的响应。

- 密钥永不回传真值，只回传 `configured` 布尔
- 每个能力附上可用状态，用户一眼能看出为什么跑不通
- 取值来自两处：能力配置（DB，`AbilitySettings`）+ 环境变量类配置（`Settings`）
"""

from __future__ import annotations

from typing import Any

from app.ability_config import AbilitySettings
from app.abilities.base import Abilities
from app.abilities.registry import config_warnings
from app.config import Settings
from app.settings_spec import (
    ABILITY_SPECS,
    EDITABLE_FIELD_NAMES,
    FIELD_SPECS,
    SECRET_FIELD_NAMES,
)

STATE_LABEL = {
    "ready": "可用",
    "missing_key": "缺少配置",
}


def _read(name: str, settings: Settings, ability: AbilitySettings) -> Any:
    """按字段归属取值（两处字段名不重叠）。"""
    if hasattr(ability, name):
        return getattr(ability, name)
    return getattr(settings, name, None)


def split_values(
    settings: Settings, ability: AbilitySettings, overrides: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """拆成 (非密钥值, 密钥状态)。"""
    values: dict[str, Any] = {}
    secrets: dict[str, Any] = {}

    for name in EDITABLE_FIELD_NAMES:
        raw = _read(name, settings, ability)
        if name in SECRET_FIELD_NAMES:
            secrets[name] = {
                "configured": bool(raw),
                "overridden": name in overrides,
            }
        else:
            values[name] = raw

    return values, secrets


def ability_status(
    ability: AbilitySettings, abilities: Abilities
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in ABILITY_SPECS:
        name = spec["ability"]
        provider = abilities.providers.get(name, "mock")

        if provider == "mock":
            state, state_label = "ready", "Mock"
        else:
            has_key = bool(getattr(ability, f"{name}_api_key", ""))
            state = "ready" if has_key else "missing_key"
            state_label = STATE_LABEL[state]

        out.append(
            {
                "ability": name,
                "label": spec["label"],
                "signature": spec["signature"],
                "provider": provider,
                "real_implemented": spec["real_implemented"],
                "options": spec["options"],
                "state": state,
                "state_label": state_label,
                "hint": spec.get("hint", ""),
            }
        )

    return out


def build_settings_payload(
    settings: Settings,
    ability: AbilitySettings,
    abilities: Abilities,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    values, secrets = split_values(settings, ability, overrides)

    return {
        "ability_status": ability_status(ability, abilities),
        "groups": _groups(),
        "values": values,
        "secrets": secrets,
        "overridden": sorted(overrides),
        "abilities": abilities.providers,
        "warnings": config_warnings(abilities, ability),
        "storage_writable": True,
    }


def _groups() -> list[dict[str, Any]]:
    """按 group 归拢字段，保持 FIELD_SPECS 里的先后顺序。"""
    groups: list[dict[str, Any]] = []
    index: dict[str, int] = {}

    for spec in FIELD_SPECS:
        name = spec["group"]
        if name not in index:
            index[name] = len(groups)
            groups.append({"name": name, "fields": []})
        groups[index[name]]["fields"].append(spec)

    return groups

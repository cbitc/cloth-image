"""把配置组装成给前端设置页的响应。

- 密钥永不回传真值，只回传 `configured` 布尔
- 每个能力附上「是否占位实现 / 是否缺 Key」的状态，用户一眼能看出为什么跑不通
"""

from __future__ import annotations

from typing import Any

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
    "stub": "占位实现",
    "missing_key": "缺少 Key",
}


def split_values(
    settings: Settings, overrides: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """拆成 (非密钥值, 密钥状态)。"""
    values: dict[str, Any] = {}
    secrets: dict[str, Any] = {}

    for name in EDITABLE_FIELD_NAMES:
        if name in SECRET_FIELD_NAMES:
            secrets[name] = {
                "configured": bool(getattr(settings, name, "")),
                "overridden": name in overrides,
            }
        else:
            values[name] = getattr(settings, name, None)

    return values, secrets


def ability_status(settings: Settings, abilities: Abilities) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for spec in ABILITY_SPECS:
        ability = spec["ability"]
        provider = abilities.providers.get(ability, "mock")
        is_stub = provider in spec["stub_options"]

        key_attr = spec["key_field"].get(provider)
        has_key = bool(getattr(settings, key_attr, "")) if key_attr else True

        if is_stub:
            state = "stub"
        elif provider != "mock" and not has_key:
            state = "missing_key"
        else:
            state = "ready"

        out.append(
            {
                "ability": ability,
                "label": spec["label"],
                "signature": spec["signature"],
                "provider": provider,
                "options": spec["options"],
                "state": state,
                "state_label": STATE_LABEL[state],
                "hint": spec.get("option_hint", {}).get(provider, ""),
            }
        )

    return out


def build_settings_payload(
    settings: Settings, abilities: Abilities, overrides: dict[str, Any]
) -> dict[str, Any]:
    values, secrets = split_values(settings, overrides)

    return {
        "ability_status": ability_status(settings, abilities),
        "groups": _groups(),
        "values": values,
        "secrets": secrets,
        "overridden": sorted(overrides),
        "mode": abilities.mode,
        "abilities": abilities.providers,
        "warnings": config_warnings(settings, abilities),
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

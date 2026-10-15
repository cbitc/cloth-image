"""能力配置：**唯一来源是设置页（数据库）**，不读环境变量。

为什么单独一个模块（本次重构的动机）：
- 消除 `PROVIDER_MODE` 全局兜底 + 每个能力「留空回退」的隐式语义 —— 能力必须显式配置。
- 消除 `maas_*` → `vlm_*`/`image_*` → `resolved_*` 的三层凭证回退 —— 每个能力独立持有
  `base_url` / `api_key` / `model`。
- provider 按协议命名（`openai_compatible` / `openai_compatible_image`），不绑定具体厂商。

代码默认值不选择任何实现（provider 为空 = 未配置）。设置页写入的覆盖项存于 `app_setting`
表，由 `app.config.apply_overrides()` 按字段归属分流到这里。
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from app.settings_spec import ABILITY_FIELD_NAMES


class AbilitySettings(BaseModel):
    """能力直接相关的配置项。字段名与 `settings_spec.ABILITY_FIELD_NAMES` 一一对应。"""

    # 搜索服装图
    clothing_search_provider: str = ""
    clothing_search_api_key: str = ""

    # 查找材质图
    material_search_provider: str = ""
    material_search_api_key: str = ""

    # 识别服装材质
    material_identifier_provider: str = ""
    material_identifier_base_url: str = ""
    material_identifier_api_key: str = ""
    material_identifier_model: str = ""

    # 图生图生成设计图
    design_generator_provider: str = ""
    design_generator_base_url: str = ""
    design_generator_api_key: str = ""
    design_generator_model: str = ""

    # 图生图 · ComfyUI（自建服务，无密钥；`preset=custom` 时用 workflow JSON）
    design_generator_comfyui_preset: str = "qwen_image_edit"
    design_generator_comfyui_workflow: str = ""
    design_generator_comfyui_lora: str = ""
    #: 0 = 使用预设默认（预设各自决定步数 / CFG）
    design_generator_comfyui_steps: int = 0
    design_generator_comfyui_cfg: float = 0.0


#: 设置页写入的覆盖项（模块级，与 Settings 的覆盖项分离）
_ABILITY_OVERRIDES: dict[str, Any] = {}


@lru_cache
def get_ability_settings() -> AbilitySettings:
    """生效的能力配置 = 代码默认值 + 设置页覆盖项（无环境变量层）。"""
    base = AbilitySettings()
    if not _ABILITY_OVERRIDES:
        return base
    allowed = set(AbilitySettings.model_fields)
    merged = {key: value for key, value in _ABILITY_OVERRIDES.items() if key in allowed}
    return base.model_copy(update=merged)


def current_ability_overrides() -> dict[str, Any]:
    """当前生效的能力覆盖项快照。"""
    return dict(_ABILITY_OVERRIDES)


def apply_ability_overrides(values: Mapping[str, Any] | None) -> None:
    """替换能力覆盖集合并清缓存。"""
    _ABILITY_OVERRIDES.clear()
    _ABILITY_OVERRIDES.update(values or {})
    get_ability_settings.cache_clear()


def reset_ability_settings_cache() -> None:
    get_ability_settings.cache_clear()

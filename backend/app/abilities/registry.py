"""能力注册表：按能力构造实现。

配置来自两处（职责分离，均无隐式回退）：
- `app.ability_config.AbilitySettings`：设置页写入的**显式**能力配置（DB 为唯一来源）
- `app.config.Settings`：环境变量打底的共享参数（超时 / 重试 / 图片边长等）

provider 按协议命名（不绑定厂商），可选实现：
  clothing_search     : unsplash
  material_search     : unsplash
  material_identifier : openai_compatible
  design_generator    : openai_compatible_image / comfyui

未选择实现（provider 为空）的能力得到一个占位实现，调用时抛
`AbilityNotConfigured`；应用本身照常启动（保证设置页可达）。
测试可通过 `register_provider()` 注入额外实现。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.ability_config import AbilitySettings, get_ability_settings
from app.abilities.base import Abilities
from app.abilities.http import ProviderError
from app.config import Settings, get_settings
from app.settings_spec import required_fields


class UnknownProvider(ValueError):
    """provider 名写错时启动即报错，而不是等第一个任务失败才发现。"""

    def __init__(self, ability: str, name: str, allowed: set[str]) -> None:
        super().__init__(
            f"未知的 provider：{ability}={name!r}，可选值：{', '.join(sorted(allowed))}"
        )
        self.ability = ability
        self.name = name


class AbilityNotConfigured(ProviderError):
    """能力尚未选择实现（provider 为空）。"""

    def __init__(self, ability: str) -> None:
        super().__init__(
            f"能力未配置：{_missing_label(ability)} 未选择实现，请到设置页配置",
            provider=ability,
        )
        self.ability = ability


# --------------------------------------------------------------------------- #
# provider 工厂表
# --------------------------------------------------------------------------- #
ProviderFactory = Callable[[AbilitySettings, Settings], Any]

_FACTORIES: dict[str, dict[str, ProviderFactory]] = {
    "clothing_search": {},
    "material_search": {},
    "material_identifier": {},
    "design_generator": {},
}


def register_provider(ability: str, name: str, factory: ProviderFactory) -> None:
    """注册一个 provider 工厂（同名覆盖）。主要给测试注入 fake 用。"""
    if ability not in _FACTORIES:
        raise KeyError(f"未知能力：{ability}")
    _FACTORIES[ability][(name or "").strip().lower()] = factory


def _make_unsplash_clothing(ability: AbilitySettings, settings: Settings) -> Any:
    from app.abilities.clothing_search import UnsplashClothingSearchProvider

    return UnsplashClothingSearchProvider(
        access_key=ability.clothing_search_api_key,
        timeout_s=settings.provider_timeout_s,
        max_retries=settings.provider_max_retries,
    )


def _make_unsplash_material(ability: AbilitySettings, settings: Settings) -> Any:
    from app.abilities.material_search import UnsplashMaterialSearchProvider

    return UnsplashMaterialSearchProvider(
        access_key=ability.material_search_api_key,
        timeout_s=settings.provider_timeout_s,
        max_retries=settings.provider_max_retries,
    )


def _make_openai_identifier(ability: AbilitySettings, settings: Settings) -> Any:
    from app.abilities.material_identify import OpenAICompatibleVLMIdentifier

    return OpenAICompatibleVLMIdentifier(
        api_key=ability.material_identifier_api_key,
        base_url=ability.material_identifier_base_url,
        model=ability.material_identifier_model,
        top_k=settings.identify_top_k,
        timeout_s=settings.provider_timeout_s,
        max_retries=settings.provider_max_retries,
        vision_max_side=settings.vision_max_image_side,
    )


def _make_openai_image(ability: AbilitySettings, settings: Settings) -> Any:
    from app.abilities.design_generate import OpenAICompatibleImageGenerator

    return OpenAICompatibleImageGenerator(
        api_key=ability.design_generator_api_key,
        base_url=ability.design_generator_base_url,
        model=ability.design_generator_model,
        size=settings.image_size,
        max_refs=settings.image_max_refs,
        prompt_extend=settings.prompt_extend,
        timeout_s=settings.provider_timeout_s,
        max_retries=settings.provider_max_retries,
    )


def _make_comfyui_image(ability: AbilitySettings, settings: Settings) -> Any:
    from app.abilities.design_generate import ComfyUIImageGenerator

    return ComfyUIImageGenerator(
        base_url=ability.design_generator_base_url,
        model=ability.design_generator_model,
        preset=ability.design_generator_comfyui_preset,
        workflow_json=ability.design_generator_comfyui_workflow,
        lora=ability.design_generator_comfyui_lora,
        size=settings.image_size,
        steps=ability.design_generator_comfyui_steps,
        cfg=ability.design_generator_comfyui_cfg,
        max_refs=settings.image_max_refs,
        download_max_bytes=settings.download_max_bytes,
        timeout_s=settings.provider_timeout_s,
        max_retries=settings.provider_max_retries,
    )


register_provider("clothing_search", "unsplash", _make_unsplash_clothing)
register_provider("material_search", "unsplash", _make_unsplash_material)
register_provider("material_identifier", "openai_compatible", _make_openai_identifier)
register_provider("design_generator", "openai_compatible_image", _make_openai_image)
register_provider("design_generator", "comfyui", _make_comfyui_image)


# --------------------------------------------------------------------------- #
# 未配置能力的占位实现（调用即抛 AbilityNotConfigured）
# --------------------------------------------------------------------------- #
class _UnconfiguredClothingSearch:
    name = ""
    sites: list[dict] = []

    def __init__(self, ability: str) -> None:
        self._ability = ability

    def search(self, *args: Any, **kwargs: Any) -> Any:
        raise AbilityNotConfigured(self._ability)


class _UnconfiguredMaterialIdentifier:
    name = ""

    def __init__(self, ability: str) -> None:
        self._ability = ability

    def identify(self, *args: Any, **kwargs: Any) -> Any:
        raise AbilityNotConfigured(self._ability)


class _UnconfiguredMaterialSearch:
    name = ""

    def __init__(self, ability: str) -> None:
        self._ability = ability

    def search(self, *args: Any, **kwargs: Any) -> Any:
        raise AbilityNotConfigured(self._ability)


class _UnconfiguredDesignGenerator:
    name = ""

    def __init__(self, ability: str) -> None:
        self._ability = ability

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise AbilityNotConfigured(self._ability)


_UNCONFIGURED: dict[str, Any] = {
    "clothing_search": _UnconfiguredClothingSearch,
    "material_search": _UnconfiguredMaterialSearch,
    "material_identifier": _UnconfiguredMaterialIdentifier,
    "design_generator": _UnconfiguredDesignGenerator,
}


def _resolve(
    ability_name: str,
    provider: str,
    ability: AbilitySettings,
    settings: Settings,
) -> Any:
    if not provider:
        return _UNCONFIGURED[ability_name](ability_name)
    factories = _FACTORIES[ability_name]
    factory = factories.get(provider)
    if factory is None:
        raise UnknownProvider(ability_name, provider, set(factories))
    return factory(ability, settings)


def _normalize(name: str) -> str:
    """规范化 provider 名（去空格 / 小写）；空值保持为空 = 未配置。"""
    return (name or "").strip().lower()


def build_abilities(ability: AbilitySettings, settings: Settings) -> Abilities:
    """纯函数版本，便于测试直接传配置对象而不依赖环境变量 / 数据库。"""
    providers = {
        "clothing_search": _normalize(ability.clothing_search_provider),
        "material_identifier": _normalize(ability.material_identifier_provider),
        "material_search": _normalize(ability.material_search_provider),
        "design_generator": _normalize(ability.design_generator_provider),
    }

    return Abilities(
        clothing_search=_resolve(
            "clothing_search", providers["clothing_search"], ability, settings
        ),
        material_identifier=_resolve(
            "material_identifier", providers["material_identifier"], ability, settings
        ),
        material_search=_resolve(
            "material_search", providers["material_search"], ability, settings
        ),
        design_generator=_resolve(
            "design_generator", providers["design_generator"], ability, settings
        ),
        providers=providers,
    )


#: 各能力必填字段的后缀（字段名 = f"{ability}_{suffix}"）。
#: 唯一来源是 `settings_spec.ABILITY_SPECS[].required`（按 provider 区分），
#: 否则会把 comfyui 这类无需密钥的实现误判为「缺少配置」。
_FIELD_LABEL = {
    "base_url": "端点 Base URL",
    "api_key": "API Key",
    "model": "模型名",
}


def _missing_label(ability: str) -> str:
    return {
        "clothing_search": "搜索服装图",
        "material_search": "查找材质图",
        "material_identifier": "识别服装材质",
        "design_generator": "图生图生成设计图",
    }.get(ability, ability)


#: 能力名 → `Abilities` 上的属性名（目前同名，显式写出来便于以后改名）
_ABILITY_ATTRS: dict[str, str] = {
    "clothing_search": "clothing_search",
    "material_search": "material_search",
    "material_identifier": "material_identifier",
    "design_generator": "design_generator",
}


def _provider_notes(abilities: Abilities, name: str) -> list[str]:
    """provider 自报的配置问题（可选约定：`config_notes` 属性）。

    用于那些「PUT 时无法校验」的配置（如粘贴的 ComfyUI 工作流 JSON），
    让设置页能提前看到，而不是等第一次跑任务才 500。
    """
    instance = getattr(abilities, _ABILITY_ATTRS.get(name, name), None)
    notes = getattr(instance, "config_notes", None)
    return [str(note) for note in notes] if isinstance(notes, (list, tuple)) else []


def config_warnings(abilities: Abilities, ability: AbilitySettings) -> list[str]:
    """启动时提示：真实 provider 缺少端点 / Key / 模型。避免跑到一半才发现配错。"""
    warnings: list[str] = []

    for name, provider in sorted(abilities.providers.items()):
        if not provider:
            warnings.append(f"{_missing_label(name)} 未选择实现，调用会失败")
            continue
        for suffix in required_fields(name, provider):
            if not getattr(ability, f"{name}_{suffix}", ""):
                warnings.append(
                    f"{_missing_label(name)} 未配置 {_FIELD_LABEL[suffix]}，调用会失败"
                )
        warnings.extend(
            f"{_missing_label(name)}：{note}"
            for note in _provider_notes(abilities, name)
        )

    return warnings


@lru_cache
def get_abilities() -> Abilities:
    return build_abilities(get_ability_settings(), get_settings())


def reset_abilities_cache() -> None:
    get_abilities.cache_clear()

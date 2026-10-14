"""能力注册表：按能力构造实现。

配置来自两处（职责分离，均已去掉隐式回退）：
- `app.ability_config.AbilitySettings`：设置页写入的**显式**能力配置（DB 为唯一来源）
- `app.config.Settings`：环境变量打底的共享参数（超时 / 重试 / 图片边长等）

provider 按协议命名（不绑定厂商）：
  clothing_search     : mock
  material_identifier : mock | openai_compatible
  material_search     : mock
  design_generator    : mock | openai_compatible_image
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.ability_config import AbilitySettings, get_ability_settings
from app.abilities.base import Abilities
from app.config import Settings, get_settings


class UnknownProvider(ValueError):
    """provider 名写错时启动即报错，而不是等第一个任务失败才发现。"""

    def __init__(self, ability: str, name: str, allowed: set[str]) -> None:
        super().__init__(
            f"未知的 provider：{ability}={name!r}，可选值：{', '.join(sorted(allowed))}"
        )
        self.ability = ability
        self.name = name


def _build_clothing_search(
    name: str, ability: AbilitySettings, settings: Settings
) -> Any:
    if name == "mock":
        from app.abilities.clothing_search import MockClothingSearchProvider

        return MockClothingSearchProvider()
    if name == "unsplash":
        from app.abilities.clothing_search import UnsplashClothingSearchProvider

        return UnsplashClothingSearchProvider(
            access_key=ability.clothing_search_api_key,
            timeout_s=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )
    raise UnknownProvider("clothing_search", name, {"mock", "unsplash"})


def _build_material_search(
    name: str, ability: AbilitySettings, settings: Settings
) -> Any:
    if name == "mock":
        from app.abilities.material_search import MockMaterialImageSearchProvider

        return MockMaterialImageSearchProvider()
    if name == "unsplash":
        from app.abilities.material_search import UnsplashMaterialSearchProvider

        return UnsplashMaterialSearchProvider(
            access_key=ability.material_search_api_key,
            timeout_s=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )
    raise UnknownProvider("material_search", name, {"mock", "unsplash"})


def _build_material_identifier(
    name: str, ability: AbilitySettings, settings: Settings
) -> Any:
    if name == "mock":
        from app.abilities.material_identify import MockMaterialIdentifier

        return MockMaterialIdentifier()
    if name == "openai_compatible":
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
    raise UnknownProvider("material_identifier", name, {"mock", "openai_compatible"})


def _build_design_generator(
    name: str, ability: AbilitySettings, settings: Settings
) -> Any:
    if name == "mock":
        from app.abilities.design_generate import MockDesignGenerator

        return MockDesignGenerator()
    if name == "openai_compatible_image":
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
    raise UnknownProvider("design_generator", name, {"mock", "openai_compatible_image"})


def _normalize(name: str) -> str:
    return (name or "mock").strip().lower() or "mock"


def _compute_mode(providers: dict[str, str]) -> str:
    real = [provider for provider in providers.values() if provider != "mock"]
    if not real:
        return "mock"
    if len(real) == len(providers):
        return "real"
    return "mixed"


def build_abilities(ability: AbilitySettings, settings: Settings) -> Abilities:
    """纯函数版本，便于测试直接传配置对象而不依赖环境变量 / 数据库。"""
    clothing_provider = _normalize(ability.clothing_search_provider)
    material_provider = _normalize(ability.material_search_provider)
    identifier_provider = _normalize(ability.material_identifier_provider)
    generator_provider = _normalize(ability.design_generator_provider)

    providers = {
        "clothing_search": clothing_provider,
        "material_identifier": identifier_provider,
        "material_search": material_provider,
        "design_generator": generator_provider,
    }

    return Abilities(
        clothing_search=_build_clothing_search(clothing_provider, ability, settings),
        material_identifier=_build_material_identifier(
            identifier_provider, ability, settings
        ),
        material_search=_build_material_search(material_provider, ability, settings),
        design_generator=_build_design_generator(generator_provider, ability, settings),
        mode=_compute_mode(providers),
        providers=providers,
    )


#: 各能力选中真实 provider 后必须填的字段（字段名 = f"{ability}_{suffix}"）
_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "clothing_search": ("api_key",),
    "material_search": ("api_key",),
    "material_identifier": ("base_url", "api_key", "model"),
    "design_generator": ("base_url", "api_key", "model"),
}

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


def config_warnings(abilities: Abilities, ability: AbilitySettings) -> list[str]:
    """启动时提示：真实 provider 缺少端点 / Key / 模型。避免跑到一半才发现配错。"""
    warnings: list[str] = []

    for name, provider in sorted(abilities.providers.items()):
        if provider == "mock":
            continue
        for suffix in _REQUIRED_FIELDS.get(name, ()):
            if not getattr(ability, f"{name}_{suffix}", ""):
                warnings.append(
                    f"{_missing_label(name)} 未配置 {_FIELD_LABEL[suffix]}，调用会失败"
                )

    return warnings


@lru_cache
def get_abilities() -> Abilities:
    return build_abilities(get_ability_settings(), get_settings())


def reset_abilities_cache() -> None:
    get_abilities.cache_clear()

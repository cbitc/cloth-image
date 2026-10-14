"""能力注册表：**按能力分别**选择 mock / 真实实现。

为什么不只是一个全局开关：`PROVIDER_MODE=real` 会把四个能力一起切成真实实现，
而只要有一个还是空壳（serpapi / fal），整条流水线就会立刻报错。
因此支持按能力覆盖，留空则回退到 `provider_mode`：

    PROVIDER_MODE=mock                    # 全局兜底
    MATERIAL_IDENTIFIER_PROVIDER=maas     # 只把材质识别切到真实 VLM
    DESIGN_GENERATOR_PROVIDER=dashscope   # 只把生图切到真实模型

这样在只接通部分 provider 时，其余环节仍可用 mock 正常跑通。

可选值：
  clothing_search     : mock | serpapi
  material_identifier : mock | maas
  material_search     : mock | serpapi
  design_generator    : mock | dashscope | fal
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from app.abilities.base import Abilities
from app.config import Settings, get_settings

#: 仍是占位实现的能力 —— 选中后会在**调用时**抛 NotImplementedError
STUB_PROVIDERS: dict[str, str] = {
    "serpapi": "app/abilities/clothing_search/serpapi.py、app/abilities/material_search/serpapi.py",
    "fal": "app/abilities/design_generate/fal.py",
}


class UnknownProvider(ValueError):
    """provider 名写错时启动即报错，而不是等第一个任务失败才发现。"""

    def __init__(self, ability: str, name: str, allowed: set[str]) -> None:
        super().__init__(
            f"未知的 provider：{ability}={name!r}，可选值：{', '.join(sorted(allowed))}"
        )
        self.ability = ability
        self.name = name


def _build_clothing_search(name: str, settings: Settings) -> Any:
    if name == "mock":
        from app.abilities.clothing_search import MockClothingSearchProvider

        return MockClothingSearchProvider()
    if name == "serpapi":
        from app.abilities.clothing_search import SerpApiClothingSearchProvider

        return SerpApiClothingSearchProvider(settings.serpapi_api_key)
    raise UnknownProvider("clothing_search", name, {"mock", "serpapi"})


def _build_material_identifier(name: str, settings: Settings) -> Any:
    if name == "mock":
        from app.abilities.material_identify import MockMaterialIdentifier

        return MockMaterialIdentifier()
    if name == "maas":
        from app.abilities.material_identify import OpenAICompatibleVLMIdentifier

        return OpenAICompatibleVLMIdentifier(
            api_key=settings.resolved_vlm_api_key,
            base_url=settings.resolved_vlm_base_url,
            model=settings.vlm_model,
            top_k=settings.identify_top_k,
            timeout_s=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
            vision_max_side=settings.vision_max_image_side,
        )
    raise UnknownProvider("material_identifier", name, {"mock", "maas"})


def _build_material_search(name: str, settings: Settings) -> Any:
    if name == "mock":
        from app.abilities.material_search import MockMaterialImageSearchProvider

        return MockMaterialImageSearchProvider()
    if name == "serpapi":
        from app.abilities.material_search import SerpApiMaterialSearchProvider

        return SerpApiMaterialSearchProvider(settings.serpapi_api_key)
    raise UnknownProvider("material_search", name, {"mock", "serpapi"})


def _build_design_generator(name: str, settings: Settings) -> Any:
    if name == "mock":
        from app.abilities.design_generate import MockDesignGenerator

        return MockDesignGenerator()
    if name == "dashscope":
        from app.abilities.design_generate import QwenImageGenerator

        return QwenImageGenerator(
            api_key=settings.resolved_image_api_key,
            base_url=settings.resolved_image_base_url,
            model=settings.image_model,
            size=settings.image_size,
            max_refs=settings.image_max_refs,
            prompt_extend=settings.prompt_extend,
            timeout_s=settings.provider_timeout_s,
            max_retries=settings.provider_max_retries,
        )
    if name == "fal":
        from app.abilities.design_generate import FalDesignGenerator

        return FalDesignGenerator(settings.fal_key)
    raise UnknownProvider("design_generator", name, {"mock", "dashscope", "fal"})


_BUILDERS: dict[str, Callable[[str, Settings], Any]] = {
    "clothing_search": _build_clothing_search,
    "material_identifier": _build_material_identifier,
    "material_search": _build_material_search,
    "design_generator": _build_design_generator,
}


def _compute_mode(providers: dict[str, str]) -> str:
    real = [provider for provider in providers.values() if provider != "mock"]
    if not real:
        return "mock"
    if len(real) == len(providers):
        return "real"
    return "mixed"


def build_abilities(settings: Settings) -> Abilities:
    """纯函数版本，便于测试直接传 Settings 而不依赖环境变量。"""
    providers = settings.providers
    built = {
        ability: _BUILDERS[ability](provider, settings)
        for ability, provider in providers.items()
    }
    return Abilities(
        clothing_search=built["clothing_search"],
        material_identifier=built["material_identifier"],
        material_search=built["material_search"],
        design_generator=built["design_generator"],
        mode=_compute_mode(providers),
        providers=providers,
    )


def config_warnings(settings: Settings, abilities: Abilities) -> list[str]:
    """启动时提示：占位实现、缺失的 Key。避免跑到一半才发现配错。"""
    warnings: list[str] = []

    for ability, provider in sorted(abilities.providers.items()):
        if provider in STUB_PROVIDERS:
            warnings.append(
                f"{ability} 使用占位实现 {provider}，调用时会抛 NotImplementedError；"
                f"实现在 {STUB_PROVIDERS[provider]}"
            )

    identifier = abilities.providers.get("material_identifier")
    if identifier == "maas" and not settings.resolved_vlm_api_key:
        warnings.append(
            "material_identifier=maas 但未配置 MAAS_API_KEY，调用会鉴权失败"
        )

    generator = abilities.providers.get("design_generator")
    if generator == "dashscope" and not settings.resolved_image_api_key:
        warnings.append(
            "design_generator=dashscope 但未配置 MAAS_API_KEY，调用会鉴权失败"
        )

    return warnings


@lru_cache
def get_abilities() -> Abilities:
    return build_abilities(get_settings())


def reset_abilities_cache() -> None:
    get_abilities.cache_clear()

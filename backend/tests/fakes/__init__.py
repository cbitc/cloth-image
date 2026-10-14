"""测试用 fake 能力实现（非生产代码）。

这些实现原先位于 `app/abilities/**/mock.py`，现已从生产代码移出，
只为测试提供确定性、零外部依赖的能力实现。

用法（在 conftest 中）::

    from fakes import register_fake_providers

    register_fake_providers()
    # 再把各能力的 provider 设为 "fake"（写 app_setting 或 AbilitySettings）
"""

from __future__ import annotations

from fakes.clothing_search import FakeClothingSearchProvider
from fakes.design_generate import FakeDesignGenerator
from fakes.material_identify import FakeMaterialIdentifier
from fakes.material_search import FakeMaterialImageSearchProvider

__all__ = [
    "FakeClothingSearchProvider",
    "FakeDesignGenerator",
    "FakeMaterialIdentifier",
    "FakeMaterialImageSearchProvider",
    "register_fake_providers",
]


def register_fake_providers() -> None:
    """把四个 fake 实现注册为 provider 名 ``fake``。"""
    from app.abilities.registry import register_provider

    register_provider(
        "clothing_search",
        "fake",
        lambda ability, settings: FakeClothingSearchProvider(),
    )
    register_provider(
        "material_identifier",
        "fake",
        lambda ability, settings: FakeMaterialIdentifier(),
    )
    register_provider(
        "material_search",
        "fake",
        lambda ability, settings: FakeMaterialImageSearchProvider(),
    )
    register_provider(
        "design_generator",
        "fake",
        lambda ability, settings: FakeDesignGenerator(),
    )

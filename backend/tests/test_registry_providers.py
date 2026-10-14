"""按能力构造 provider 的注册表测试。

核心保证：能力配置是**显式**的（无全局兜底、无留空回退、无空壳 provider）；
未选择实现的能力会得到占位实现，调用时抛 `AbilityNotConfigured`。
"""

from __future__ import annotations

import pytest

from app.ability_config import AbilitySettings
from app.abilities.clothing_search import UnsplashClothingSearchProvider
from app.abilities.design_generate import OpenAICompatibleImageGenerator
from app.abilities.material_identify import OpenAICompatibleVLMIdentifier
from app.abilities.material_search import UnsplashMaterialSearchProvider
from app.abilities.registry import (
    AbilityNotConfigured,
    UnknownProvider,
    build_abilities,
    config_warnings,
)
from app.config import Settings
from fakes import (
    FakeClothingSearchProvider,
    FakeDesignGenerator,
    FakeMaterialIdentifier,
    FakeMaterialImageSearchProvider,
)


def _settings(**overrides) -> Settings:
    base: dict = {"database_url": "sqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


def _fake_all(**overrides) -> AbilitySettings:
    base: dict = {
        "clothing_search_provider": "fake",
        "material_search_provider": "fake",
        "material_identifier_provider": "fake",
        "design_generator_provider": "fake",
    }
    base.update(overrides)
    return AbilitySettings(**base)


def _identifier(**overrides) -> AbilitySettings:
    base: dict = {
        "material_identifier_provider": "openai_compatible",
        "material_identifier_base_url": "https://endpoint.test/v1",
        "material_identifier_api_key": "test-key",
        "material_identifier_model": "qwen3-vl-plus",
    }
    base.update(overrides)
    return AbilitySettings(**base)


def _generator(**overrides) -> AbilitySettings:
    base: dict = {
        "design_generator_provider": "openai_compatible_image",
        "design_generator_base_url": "https://endpoint.test/v1",
        "design_generator_api_key": "test-key",
        "design_generator_model": "qwen-image-3.0",
    }
    base.update(overrides)
    return AbilitySettings(**base)


def _unsplash(**overrides) -> AbilitySettings:
    base: dict = {
        "clothing_search_provider": "unsplash",
        "clothing_search_api_key": "test-access-key",
    }
    base.update(overrides)
    return AbilitySettings(**base)


def _unsplash_material(**overrides) -> AbilitySettings:
    base: dict = {
        "material_search_provider": "unsplash",
        "material_search_api_key": "test-access-key",
    }
    base.update(overrides)
    return AbilitySettings(**base)


def test_fake_providers_are_built_when_selected() -> None:
    abilities = build_abilities(_fake_all(), _settings())

    assert set(abilities.providers.values()) == {"fake"}
    assert isinstance(abilities.clothing_search, FakeClothingSearchProvider)
    assert isinstance(abilities.material_identifier, FakeMaterialIdentifier)
    assert isinstance(abilities.material_search, FakeMaterialImageSearchProvider)
    assert isinstance(abilities.design_generator, FakeDesignGenerator)


def test_unconfigured_ability_raises_clear_error() -> None:
    abilities = build_abilities(AbilitySettings(), _settings())

    assert abilities.providers["material_identifier"] == ""
    with pytest.raises(AbilityNotConfigured) as info:
        abilities.material_identifier.identify(b"x")
    assert "识别服装材质" in str(info.value)


def test_material_search_can_use_unsplash() -> None:
    abilities = build_abilities(_unsplash_material(), _settings())
    assert abilities.providers["material_search"] == "unsplash"
    assert isinstance(abilities.material_search, UnsplashMaterialSearchProvider)


def test_unsplash_material_missing_key_emits_warning() -> None:
    ability = _unsplash_material(material_search_api_key="")
    warnings = config_warnings(build_abilities(ability, _settings()), ability)
    assert any("查找材质图" in warning for warning in warnings)
    assert any("API Key" in warning for warning in warnings)


def test_clothing_search_can_use_unsplash() -> None:
    abilities = build_abilities(_unsplash(), _settings())
    assert abilities.providers["clothing_search"] == "unsplash"
    assert isinstance(abilities.clothing_search, UnsplashClothingSearchProvider)


def test_unsplash_missing_key_emits_warning() -> None:
    ability = _unsplash(clothing_search_api_key="")
    warnings = config_warnings(build_abilities(ability, _settings()), ability)
    assert any("搜索服装图" in warning for warning in warnings)
    assert any("API Key" in warning for warning in warnings)


def test_switching_one_ability_leaves_others_unconfigured() -> None:
    abilities = build_abilities(_identifier(), _settings())

    assert isinstance(abilities.material_identifier, OpenAICompatibleVLMIdentifier)
    assert abilities.providers["design_generator"] == ""
    with pytest.raises(AbilityNotConfigured):
        abilities.design_generator.generate([], "x")


def test_identifier_receives_explicit_config() -> None:
    abilities = build_abilities(
        _identifier(material_identifier_model="qwen3-vl-max"), _settings()
    )

    identifier = abilities.material_identifier
    assert isinstance(identifier, OpenAICompatibleVLMIdentifier)
    assert identifier.model == "qwen3-vl-max"
    assert identifier.base_url == "https://endpoint.test/v1"


def test_image_generator_receives_shared_settings() -> None:
    abilities = build_abilities(
        _generator(design_generator_model="qwen-image-3.0-pro"),
        _settings(image_size="768x1024", image_max_refs=2),
    )

    generator = abilities.design_generator
    assert isinstance(generator, OpenAICompatibleImageGenerator)
    assert generator.model == "qwen-image-3.0-pro"
    assert generator.size == "768x1024"
    assert generator.base_url == "https://endpoint.test/v1"


def test_unknown_provider_fails_fast_with_helpful_message() -> None:
    with pytest.raises(UnknownProvider) as info:
        build_abilities(
            AbilitySettings(material_identifier_provider="gpt-5"), _settings()
        )

    message = str(info.value)
    assert "material_identifier" in message
    assert "openai_compatible" in message


def test_missing_api_key_emits_warning() -> None:
    ability = _identifier(material_identifier_api_key="")
    abilities = build_abilities(ability, _settings())

    warnings = config_warnings(abilities, ability)
    assert any("API Key" in warning for warning in warnings)


def test_missing_endpoint_and_model_emit_warnings() -> None:
    ability = _generator(design_generator_base_url="", design_generator_model="")
    abilities = build_abilities(ability, _settings())

    warnings = config_warnings(abilities, ability)
    assert any("Base URL" in warning for warning in warnings)
    assert any("模型" in warning for warning in warnings)


def test_unconfigured_abilities_emit_warnings() -> None:
    ability = AbilitySettings()
    warnings = config_warnings(build_abilities(ability, _settings()), ability)

    assert len(warnings) == 4
    assert all("未选择实现" in warning for warning in warnings)

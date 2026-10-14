"""按能力构造 provider 的注册表测试。

核心保证：能力配置是**显式**的（无全局兜底、无留空回退、无空壳 provider）；
只有显式选中真实 provider 的能力才会走真实实现，其余能力保持 mock。
"""

from __future__ import annotations

import pytest

from app.ability_config import AbilitySettings
from app.abilities.clothing_search import MockClothingSearchProvider
from app.abilities.design_generate import (
    MockDesignGenerator,
    OpenAICompatibleImageGenerator,
)
from app.abilities.material_identify import (
    MockMaterialIdentifier,
    OpenAICompatibleVLMIdentifier,
)
from app.abilities.material_search import MockMaterialImageSearchProvider
from app.abilities.registry import UnknownProvider, build_abilities, config_warnings
from app.config import Settings


def _settings(**overrides) -> Settings:
    base: dict = {"database_url": "sqlite:///:memory:"}
    base.update(overrides)
    return Settings(**base)


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


def test_all_mock_by_default() -> None:
    abilities = build_abilities(AbilitySettings(), _settings())

    assert abilities.mode == "mock"
    assert set(abilities.providers.values()) == {"mock"}
    assert isinstance(abilities.clothing_search, MockClothingSearchProvider)
    assert isinstance(abilities.material_identifier, MockMaterialIdentifier)
    assert isinstance(abilities.material_search, MockMaterialImageSearchProvider)
    assert isinstance(abilities.design_generator, MockDesignGenerator)
    assert abilities.real_providers == []


def test_search_abilities_are_always_mock() -> None:
    """搜索类能力没有真实实现：即使其它能力切换，它们仍是 mock。"""
    abilities = build_abilities(_identifier(), _settings())

    assert abilities.providers["clothing_search"] == "mock"
    assert abilities.providers["material_search"] == "mock"
    assert isinstance(abilities.clothing_search, MockClothingSearchProvider)
    assert isinstance(abilities.material_search, MockMaterialImageSearchProvider)


def test_switching_one_ability_yields_mixed_mode() -> None:
    abilities = build_abilities(_identifier(), _settings())

    assert abilities.mode == "mixed"
    assert isinstance(abilities.material_identifier, OpenAICompatibleVLMIdentifier)
    assert isinstance(abilities.design_generator, MockDesignGenerator)
    assert abilities.real_providers == ["material_identifier=openai_compatible"]


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
    assert "mock" in message and "openai_compatible" in message


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


def test_no_warnings_for_pure_mock_setup() -> None:
    ability = AbilitySettings()
    assert config_warnings(build_abilities(ability, _settings()), ability) == []

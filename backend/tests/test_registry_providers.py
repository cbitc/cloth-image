"""按能力切换 provider 的注册表测试。

核心保证：只把部分能力切到真实实现时，其余环节仍用 mock 正常可用
（否则 `PROVIDER_MODE=real` 会一脚踩到 serpapi / fal 空壳）。
"""

from __future__ import annotations

import pytest

from app.abilities.clothing_search import MockClothingSearchProvider
from app.abilities.design_generate import MockDesignGenerator, QwenImageGenerator
from app.abilities.material_identify import (
    MockMaterialIdentifier,
    OpenAICompatibleVLMIdentifier,
)
from app.abilities.material_search import MockMaterialImageSearchProvider
from app.abilities.registry import UnknownProvider, build_abilities, config_warnings
from app.config import Settings


def _settings(**overrides) -> Settings:
    base: dict = {
        "provider_mode": "mock",
        "database_url": "sqlite:///:memory:",
        "maas_api_key": "test-key",
        "maas_base_url": "https://maas.test/v1",
    }
    base.update(overrides)
    return Settings(**base)


def test_all_mock_when_provider_mode_is_mock() -> None:
    abilities = build_abilities(_settings())

    assert abilities.mode == "mock"
    assert set(abilities.providers.values()) == {"mock"}
    assert isinstance(abilities.clothing_search, MockClothingSearchProvider)
    assert isinstance(abilities.material_identifier, MockMaterialIdentifier)
    assert isinstance(abilities.material_search, MockMaterialImageSearchProvider)
    assert isinstance(abilities.design_generator, MockDesignGenerator)
    assert abilities.real_providers == []


def test_switching_one_ability_yields_mixed_mode() -> None:
    abilities = build_abilities(_settings(material_identifier_provider="maas"))

    assert abilities.mode == "mixed"
    assert isinstance(abilities.material_identifier, OpenAICompatibleVLMIdentifier)
    # 其余能力保持 mock，不受影响
    assert isinstance(abilities.clothing_search, MockClothingSearchProvider)
    assert isinstance(abilities.design_generator, MockDesignGenerator)
    assert abilities.real_providers == ["material_identifier=maas"]


def test_image_generator_receives_settings() -> None:
    abilities = build_abilities(
        _settings(
            design_generator_provider="dashscope", image_model="qwen-image-3.0-pro"
        )
    )

    generator = abilities.design_generator
    assert isinstance(generator, QwenImageGenerator)
    assert generator.model == "qwen-image-3.0-pro"
    assert generator.size == "1024x1024"
    assert generator.base_url == "https://maas.test/v1"


def test_provider_mode_real_is_overridable_per_ability() -> None:
    """全局 real + 单独把某能力退回 mock，是允许且有用的组合。"""
    abilities = build_abilities(
        _settings(
            provider_mode="real",
            material_identifier_provider="mock",
            design_generator_provider="mock",
            clothing_search_provider="mock",
            material_search_provider="mock",
        )
    )

    assert abilities.mode == "mock"
    assert isinstance(abilities.material_identifier, MockMaterialIdentifier)


def test_unknown_provider_fails_fast_with_helpful_message() -> None:
    with pytest.raises(UnknownProvider) as info:
        build_abilities(_settings(material_identifier_provider="gpt-5"))

    message = str(info.value)
    assert "material_identifier" in message
    assert "mock" in message and "maas" in message


def test_stub_provider_emits_warning() -> None:
    settings = _settings(clothing_search_provider="serpapi")
    abilities = build_abilities(settings)

    warnings = config_warnings(settings, abilities)
    assert any("NotImplementedError" in warning for warning in warnings)


def test_missing_api_key_emits_warning() -> None:
    settings = _settings(
        material_identifier_provider="maas", maas_api_key="", vlm_api_key=""
    )
    abilities = build_abilities(settings)

    warnings = config_warnings(settings, abilities)
    assert any("MAAS_API_KEY" in warning for warning in warnings)


def test_no_warnings_for_pure_mock_setup() -> None:
    settings = _settings()
    assert config_warnings(settings, build_abilities(settings)) == []

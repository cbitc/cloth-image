"""VLM 材质识别适配器测试。

全部使用 `httpx.MockTransport` + 无操作 sleep → 完全离线、零成本、瞬时。
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.abilities.http import (
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderError,
    RetryingHttpClient,
)
from app.abilities.material_identify import OpenAICompatibleVLMIdentifier

Handler = Callable[[httpx.Request], httpx.Response]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (300, 200), (180, 90, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _http_client(handler: Handler) -> RetryingHttpClient:
    return RetryingHttpClient(
        provider="test-vlm",
        max_retries=2,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep_fn=lambda _seconds: None,
    )


def _chat(content: str, usage: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": usage
            or {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        },
    )


def _identifier(handler: Handler, **kwargs) -> OpenAICompatibleVLMIdentifier:
    return OpenAICompatibleVLMIdentifier(
        api_key="test-key",
        base_url="https://vlm.test/v1",
        model="qwen3-vl-plus",
        http_client=_http_client(handler),
        **kwargs,
    )


CARD_JSON = {
    "category": "连衣裙",
    "color": {
        "dominant": {"hex": "#2B3A4A", "name": "深灰蓝", "lab": [35, -2, -12]},
        "palette": [
            {"hex": "#2B3A4A", "ratio": 0.72},
            {"hex": "#C8C2B8", "ratio": 0.28},
        ],
        "distribution": "整体均匀",
    },
    "pattern": {"type": "纯色", "scale": None, "direction": None, "layout": "全身"},
    "optical": {"gloss": "哑光", "transparency": "不透明"},
    "fabric": {
        "material": "桑蚕丝",
        "material_en": "Mulberry Silk",
        "confidence": 0.72,
    },
    "behavior": {"weight": "中等", "drape": "适中"},
    "confidence": {"color": 0.95, "pattern": 0.91, "gloss": 0.83},
    "evidence": "表面哑光无反射、织纹细密均匀。",
    "swatch_box": [0.3, 0.4, 0.6, 0.7],
}


def _card_chat(payload: object = CARD_JSON, *, fenced: bool = False) -> httpx.Response:
    text = json.dumps(payload, ensure_ascii=False)
    if fenced:
        text = "```json\n" + text + "\n```"
    return _chat(text)


def test_parses_card_json_crops_swatch_and_sends_data_url() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _card_chat(fenced=True)

    identifier = _identifier(handler)
    card = identifier.identify(_png(), "image/png")

    assert card.category == "连衣裙"
    region = card.primary
    assert region is not None
    assert region.color.dominant_hex == "#2B3A4A"
    assert region.color.dominant_name == "深灰蓝"
    assert region.color.lab == (35.0, -2.0, -12.0)
    assert [entry["hex"] for entry in region.color.palette] == ["#2B3A4A", "#C8C2B8"]
    assert region.pattern.type == "纯色"
    assert region.optical.gloss == "哑光"
    assert region.fabric.material == "桑蚕丝"
    assert region.fabric.category == "天然纤维"  # 由受控词表回填
    assert region.confidence.color == 0.95
    assert card.overall_confidence == pytest.approx((0.95 + 0.91 + 0.83) / 3, abs=1e-3)

    # 小样：按模型给的框真实裁剪出字节（这是生成阶段的保真锚点）
    assert region.swatch_bytes
    assert region.swatch_content_type == "image/jpeg"
    assert region.swatch_crop_box == (0.3, 0.4, 0.6, 0.7)

    assert identifier.last_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 30,
        "total_tokens": 130,
    }

    body = calls[0]
    assert body["model"] == "qwen3-vl-plus"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    image_part = body["messages"][1]["content"][1]
    # 必须是 data URL：外部服务访问不到我们的 localhost /media 地址
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # 受控词表被注入到提示里（fabric.material 只能从词表选）
    assert "桑蚕丝" in body["messages"][1]["content"][0]["text"]


def test_swatch_falls_back_to_center_crop_when_box_is_invalid() -> None:
    payload = dict(CARD_JSON, swatch_box=[0.99, 0.99, 1.4, 1.4])

    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat(payload)

    region = _identifier(handler).identify(_png()).primary
    assert region is not None
    assert region.swatch_bytes  # 框非法也要有小样（退化为中心区域）
    assert region.swatch_crop_box == (0.2, 0.2, 0.8, 0.8)


def test_swatch_can_be_disabled_by_flag() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat()

    region = _identifier(handler, swatch_enabled=False).identify(_png()).primary
    assert region is not None
    assert region.swatch_bytes is None


def test_legacy_tags_array_is_normalized_into_a_single_region() -> None:
    """模型不听话回到旧格式时，也要能拼出一张可用的卡片。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat([{"material": "棉", "confidence": 0.8, "evidence": "哑光"}])

    card = _identifier(handler).identify(_png())
    region = card.primary
    assert region is not None
    assert region.fabric.material == "棉"
    assert region.fabric.category == "天然纤维"
    assert region.pattern.type == "纯色"  # 缺字段 → 受控默认值
    assert region.behavior.is_default is True


def test_english_material_name_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat({"fabric": {"material": "mulberry silk", "confidence": 0.8}})

    region = _identifier(handler).identify(_png()).primary
    assert region is not None
    assert region.fabric.material == "桑蚕丝"
    assert region.fabric.material_en == "Mulberry Silk"


def test_unknown_material_is_kept_but_has_no_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat({"fabric": {"material": "外星纤维", "confidence": 0.6}})

    region = _identifier(handler).identify(_png()).primary
    assert region is not None
    assert region.fabric.material == "外星纤维"
    assert region.fabric.category == ""


def test_enum_values_are_coerced_and_confidence_clamped() -> None:
    payload = {
        "category": "dress",
        "pattern": {"type": "solid"},
        "optical": {"gloss": "matte", "transparency": "opaque"},
        "behavior": {"weight": "heavy", "drape": "stiff"},
        "fabric": {"material": "棉", "confidence": 1.7},
        "confidence": {"color": 1.9, "pattern": -2, "gloss": "not-a-number"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat(payload)

    card = _identifier(handler).identify(_png())
    region = card.primary
    assert region is not None
    assert card.category == "连衣裙"
    assert region.pattern.type == "纯色"
    assert region.optical.gloss == "哑光"
    assert region.optical.transparency == "不透明"
    assert region.behavior.weight == "厚重"
    assert region.behavior.drape == "挺括"
    assert region.behavior.is_default is False  # 模型给了值就不是默认值
    assert region.fabric.confidence == 1.0
    assert region.confidence.color == 1.0
    assert region.confidence.pattern == 0.0
    assert region.confidence.gloss == 0.0


def test_palette_ratios_are_normalized_to_one() -> None:
    payload = {
        "color": {
            "dominant": {"hex": "2b3a4a"},
            "palette": [
                {"hex": "#2B3A4A", "ratio": 72},
                {"hex": "#C8C2B8", "ratio": 28},
                {"hex": "oops", "ratio": 5},
            ],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _card_chat(payload)

    region = _identifier(handler).identify(_png()).primary
    assert region is not None
    assert region.color.dominant_hex == "#2B3A4A"  # 缺 # 自动补全并大写
    assert [entry["hex"] for entry in region.color.palette] == ["#2B3A4A", "#C8C2B8"]
    assert sum(entry["ratio"] for entry in region.color.palette) == pytest.approx(1.0)


def test_auth_error_is_readable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    with pytest.raises(ProviderAuthError) as info:
        _identifier(handler).identify(_png())

    assert "鉴权失败" in str(info.value)
    assert info.value.status == 401


def test_retries_on_5xx_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, text="upstream busy")
        return _chat(
            json.dumps([{"material": "棉", "confidence": 0.9, "evidence": "x"}])
        )

    card = _identifier(handler).identify(_png())
    assert attempts["count"] == 2
    assert card.primary is not None
    assert card.primary.fabric.material == "棉"


def test_response_format_is_always_sent_and_rejection_propagates() -> None:
    sent: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append("response_format" in body)
        return httpx.Response(
            400, json={"error": {"message": "response_format is not supported"}}
        )

    with pytest.raises(ProviderBadRequestError):
        _identifier(handler).identify(_png())

    assert sent == [True]  # 始终携带 response_format，不再降级重试


def test_missing_image_data_raises_before_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("缺少图片时不应发起请求")

    with pytest.raises(ProviderError):
        _identifier(handler).identify(None, "image/png", image_url="")


def test_public_url_is_passed_through_instead_of_downloading() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _card_chat(fenced=True)

    _identifier(handler).identify(None, image_url="https://cdn.example.com/a.jpg")
    part = calls[0]["messages"][1]["content"][1]
    assert part["image_url"]["url"] == "https://cdn.example.com/a.jpg"


def test_non_json_response_raises_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    with pytest.raises(ProviderError) as info:
        _identifier(handler).identify(_png())
    assert "非 JSON" in str(info.value)

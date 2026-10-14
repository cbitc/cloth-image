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

from app.abilities.http import ProviderAuthError, ProviderError, RetryingHttpClient
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


def test_parses_fenced_json_caps_top_k_and_sends_data_url() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        payload = {
            "tags": [
                {
                    "material": "桑蚕丝",
                    "confidence": 0.9,
                    "evidence": "强光泽、细腻垂坠",
                },
                {"material": "醋酸", "confidence": 0.7, "evidence": "光泽强但偏硬"},
                {"material": "雪纺", "confidence": 0.5, "evidence": "轻薄透视"},
                {"material": "蕾丝", "confidence": 0.4, "evidence": "镂空织纹"},
            ]
        }
        return _chat("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")

    identifier = _identifier(handler, top_k=3)
    tags = identifier.identify(_png(), "image/png")

    assert [tag.material for tag in tags] == ["桑蚕丝", "醋酸", "雪纺"]
    assert [tag.rank for tag in tags] == [0, 1, 2]
    assert tags[0].category == "天然纤维"  # 由受控词表回填
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
    # 受控词表被注入到提示里
    assert "桑蚕丝" in body["messages"][1]["content"][0]["text"]


def test_bare_array_response_is_accepted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat(
            json.dumps([{"material": "棉", "confidence": 0.8, "evidence": "哑光"}])
        )

    tags = _identifier(handler).identify(_png())
    assert tags[0].material == "棉"
    assert tags[0].category == "天然纤维"


def test_english_name_is_normalized_and_deduped() -> None:
    """模型用英文名回同一个材质时，应归一到中文并只保留最高置信度那条。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat(
            json.dumps(
                [
                    {"material": "桑蚕丝", "confidence": 0.5, "evidence": "a"},
                    {"material": "mulberry silk", "confidence": 0.8, "evidence": "b"},
                ]
            )
        )

    tags = _identifier(handler).identify(_png())
    assert len(tags) == 1
    assert tags[0].material == "桑蚕丝"
    assert tags[0].confidence == 0.8


def test_unknown_material_is_kept_but_has_no_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat(
            json.dumps([{"material": "外星纤维", "confidence": 0.6, "evidence": "x"}])
        )

    tags = _identifier(handler).identify(_png())
    assert tags[0].material == "外星纤维"
    assert tags[0].category == ""


def test_confidence_is_clamped_and_sorted_descending() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat(
            json.dumps(
                [
                    {"material": "棉", "confidence": 1.7, "evidence": "x"},
                    {"material": "亚麻", "confidence": -3, "evidence": "y"},
                    {"material": "羊毛", "confidence": "not-a-number", "evidence": "z"},
                ]
            )
        )

    tags = _identifier(handler).identify(_png())
    by_name = {tag.material: tag.confidence for tag in tags}
    assert by_name["棉"] == 1.0
    assert by_name["亚麻"] == 0.0
    assert by_name["羊毛"] == 0.0
    confidences = [tag.confidence for tag in tags]
    assert confidences == sorted(confidences, reverse=True)


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

    tags = _identifier(handler).identify(_png())
    assert attempts["count"] == 2
    assert tags[0].material == "棉"


def test_falls_back_when_response_format_is_rejected() -> None:
    sent_response_format: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent_response_format.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(
                400, json={"error": {"message": "response_format is not supported"}}
            )
        return _chat(
            json.dumps(
                {"tags": [{"material": "涤纶", "confidence": 0.8, "evidence": "x"}]}
            )
        )

    tags = _identifier(handler).identify(_png())
    assert sent_response_format == [True, False]  # 先带后剥，各一次
    assert tags[0].material == "涤纶"


def test_missing_image_data_raises_before_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("缺少图片时不应发起请求")

    with pytest.raises(ProviderError):
        _identifier(handler).identify(None, "image/png", image_url="")


def test_public_url_is_passed_through_instead_of_downloading() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return _chat(
            json.dumps([{"material": "棉", "confidence": 0.7, "evidence": "x"}])
        )

    _identifier(handler).identify(None, image_url="https://cdn.example.com/a.jpg")
    part = calls[0]["messages"][1]["content"][1]
    assert part["image_url"]["url"] == "https://cdn.example.com/a.jpg"


def test_non_json_response_raises_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway error</html>")

    with pytest.raises(ProviderError) as info:
        _identifier(handler).identify(_png())
    assert "非 JSON" in str(info.value)

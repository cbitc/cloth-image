"""ComfyUI 生图适配器测试（离线，httpx.MockTransport）。

重点覆盖实测踩到的坑：
  - 参考图必须**上传**（ComfyUI 读不到我们的 localhost /media）
  - `/prompt` 的 400 + node_errors 要把可读原因带出来
  - `/history` 在任务结束前返回空对象 → 必须轮询
  - 预设把提示词/尺寸/seed 注进正确的节点；自定义工作流靠结构化推断注入
  - 每个候选独立跑一次（seed 不同），参考图只上传一次
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from app.abilities.base import MaterialImageResult, ReferenceImage
from app.abilities.design_generate import ComfyUIImageGenerator
from app.abilities.design_generate.comfyui_workflows import (
    align_to_latent,
    parse_workflow,
    validate_custom_workflow,
)
from app.abilities.http import (
    ProviderBadRequestError,
    ProviderError,
    RetryingHttpClient,
)

Handler = Callable[[httpx.Request], httpx.Response]

_FILENAME_RE = re.compile(r'filename="([^"]+)"')
_DESIGN_IDEA = "改成收腰版型，裙摆加长到脚踝，保留原立领"


def _png(color: tuple[int, int, int] = (200, 60, 60), size: int = 96) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _material(
    tag: str, similarity: float = 0.5, color=(10, 20, 30)
) -> MaterialImageResult:
    return MaterialImageResult(tag=tag, similarity=similarity, image_bytes=_png(color))


def _custom_workflow_json() -> str:
    """一份最小可用的「用户自带」工作流（API 格式）。"""
    graph = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "my-model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "占位正向"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["1", 1], "text": "占位负向"},
        },
        "4": {"class_type": "LoadImage", "inputs": {"image": "my-ref.png"}},
        "5": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": 512, "height": 512, "batch_size": 1},
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": 0,
                "steps": 20,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": "user"},
        },
    }
    return json.dumps(graph, ensure_ascii=False)


def _server(
    *,
    history_calls_before_done: int = 1,
    history_failures: int = 0,
    status: dict | None = None,
    outputs: dict | None = None,
    prompt_response: dict | None = None,
    prompt_status: int = 200,
    fail_uploads: bool = False,
) -> tuple[Handler, dict]:
    """搭一个最小 ComfyUI：上传 → 提交 → 轮询 → 取图。"""
    state: dict = {"uploads": [], "graphs": [], "history_calls": 0}
    done_status = (
        status if status is not None else {"status_str": "success", "completed": True}
    )
    then_outputs = (
        outputs
        if outputs is not None
        else {
            "16": {
                "images": [
                    {
                        "filename": "cloth-design_00001_.png",
                        "subfolder": "",
                        "type": "output",
                    }
                ]
            }
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path == "/upload/image":
            if fail_uploads:
                return httpx.Response(500, text="upload boom")
            body = request.content.decode("utf-8", errors="ignore")
            names = _FILENAME_RE.findall(body)
            state["uploads"].append(names[0] if names else "?")
            return httpx.Response(
                200,
                json={"name": "cloth_ref_abc.jpg", "subfolder": "", "type": "input"},
            )

        if path == "/prompt":
            state["graphs"].append(json.loads(request.content))
            if prompt_status >= 400:
                return httpx.Response(prompt_status, json=prompt_response or {})
            return httpx.Response(
                200, json=prompt_response or {"prompt_id": "p1", "number": 1}
            )

        if path.startswith("/history/"):
            state["history_calls"] += 1
            if state["history_calls"] <= history_failures:
                return httpx.Response(503, text="server busy")
            polls = state["history_calls"] - history_failures
            if polls <= history_calls_before_done:
                return httpx.Response(200, json={})
            prompt_id = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={prompt_id: {"outputs": then_outputs, "status": done_status}},
            )

        if path == "/view":
            return httpx.Response(
                200, content=_png((10, 200, 10)), headers={"content-type": "image/png"}
            )

        if path == "/system_stats":
            return httpx.Response(200, json={"system": {"comfyui_version": "0.36.0"}})

        if path.startswith("/object_info/"):
            node = path.rsplit("/", 1)[-1]
            options = {
                "UNETLoader": ["Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors"],
                "CLIPLoader": ["qwen_2.5_vl_7b_fp8_scaled.safetensors"],
                "VAELoader": ["qwen_image_vae.safetensors"],
                "LoraLoaderModelOnly": [
                    "Qwen-Image-Edit-Lightning-4steps-V1.0-bf16.safetensors"
                ],
            }.get(node)
            if options is None:
                return httpx.Response(404, text="node not found")
            field = {
                "UNETLoader": "unet_name",
                "CLIPLoader": "clip_name",
                "VAELoader": "vae_name",
                "LoraLoaderModelOnly": "lora_name",
            }[node]
            return httpx.Response(
                200, json={node: {"input": {"required": {field: [options, {}]}}}}
            )

        return httpx.Response(404, text=f"unexpected path: {path}")

    return handler, state


def _generator(handler: Handler, **kwargs) -> ComfyUIImageGenerator:
    kwargs.setdefault("seed_fn", lambda: 12345)
    return ComfyUIImageGenerator(
        base_url="http://comfy.test:8188",
        http_client=RetryingHttpClient(
            provider="test-comfy",
            max_retries=0,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            sleep_fn=lambda _seconds: None,
        ),
        poll_interval_s=0.0,
        sleep_fn=lambda _seconds: None,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# qwen_image_edit 预设
# --------------------------------------------------------------------------- #
def test_qwen_preset_uploads_refs_and_returns_image_bytes() -> None:
    handler, state = _server()
    generator = _generator(handler)

    results = generator.generate(
        [_material("棉", 0.9, (11, 22, 33)), _material("丝", 0.8, (44, 55, 66))],
        _DESIGN_IDEA,
        ReferenceImage(image_bytes=_png(), caption="原服装图"),
        num_candidates=1,
    )

    assert len(results) == 1
    assert results[0].image_bytes and results[0].image_bytes.startswith(b"\x89PNG")
    assert results[0].content_type == "image/png"
    assert results[0].seed == 12345
    assert results[0].model == "Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors"
    assert _DESIGN_IDEA in results[0].prompt

    # 原服装图 + 两张材质图 → 3 次上传
    assert len(state["uploads"]) == 3

    graph = state["graphs"][0]["prompt"]
    assert (
        graph["1"]["inputs"]["unet_name"]
        == "Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors"
    )
    assert graph["2"]["inputs"]["type"] == "qwen_image"
    assert graph["10"]["class_type"] == "TextEncodeQwenImageEditPlus"
    assert _DESIGN_IDEA in graph["10"]["inputs"]["prompt"]
    assert graph["10"]["inputs"]["image1"] == ["20", 0]
    assert graph["10"]["inputs"]["image2"] == ["21", 0]
    assert graph["10"]["inputs"]["image3"] == ["22", 0]
    # 有参考图 → latent 来自参考图的 VAEEncode（编辑语义），不是空 latent
    assert graph["13"]["class_type"] == "VAEEncode"
    assert graph["12"]["inputs"]["width"] == 1024
    assert graph["14"]["inputs"]["seed"] == 12345


def test_material_refs_deduped_per_tag_and_truncated_to_max_refs() -> None:
    handler, state = _server()
    generator = _generator(handler, max_refs=3)

    materials = [
        _material("棉", 0.95, (1, 2, 3)),
        _material("棉", 0.60, (4, 5, 6)),  # 同 tag 的低分图应被丢掉
        _material("丝", 0.90, (7, 8, 9)),
        _material("麻", 0.85, (10, 11, 12)),
        _material("毛", 0.80, (13, 14, 15)),
    ]

    generator.generate(materials, _DESIGN_IDEA, num_candidates=1)

    # 原服装图为 None → 只上传材质图，且被 max_refs=3 截断
    assert len(state["uploads"]) == 3


def test_identical_reference_bytes_are_uploaded_once() -> None:
    """同一张图重复出现（如同一 tag 的高低分副本）只上传一次。"""
    handler, state = _server()
    generator = _generator(handler, max_refs=4)
    same = _png((9, 9, 9))

    generator.generate(
        [
            MaterialImageResult(tag="棉", similarity=0.9, image_bytes=same),
            MaterialImageResult(tag="丝", similarity=0.8, image_bytes=same),
        ],
        _DESIGN_IDEA,
        num_candidates=1,
    )

    assert len(state["uploads"]) == 1


def test_without_any_reference_falls_back_to_empty_latent() -> None:
    handler, state = _server(
        outputs={
            "16": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}
        }
    )
    generator = _generator(handler)

    generator.generate([], _DESIGN_IDEA, num_candidates=1)

    assert state["uploads"] == []
    graph = state["graphs"][0]["prompt"]
    assert graph["13"]["class_type"] == "EmptySD3LatentImage"
    assert "image1" not in graph["10"]["inputs"]
    assert "20" not in graph


def test_each_candidate_is_a_separate_run_with_own_seed() -> None:
    handler, state = _server()
    seeds = iter([111, 222, 333])
    generator = _generator(handler, seed_fn=lambda: next(seeds))

    results = generator.generate([_material("棉")], _DESIGN_IDEA, num_candidates=3)

    assert [r.seed for r in results] == [111, 222, 333]
    assert [r.rank for r in results] == [0, 1, 2]
    assert len(state["graphs"]) == 3
    # 参考图对三个候选相同 → 只上传一次
    assert len(state["uploads"]) == 1


def test_image_size_is_aligned_and_applied() -> None:
    handler, state = _server()
    generator = _generator(handler, size="1000x1003")

    generator.generate([], "x", num_candidates=1)

    latent = state["graphs"][0]["prompt"]["13"]["inputs"]
    assert latent["width"] == 992  # 向下对齐到 16 的倍数
    assert latent["height"] == 992


def test_lightning_lora_switches_to_four_steps() -> None:
    handler, state = _server()
    generator = _generator(
        handler, lora="Qwen-Image-Edit-Lightning-4steps-V1.0-bf16.safetensors"
    )

    generator.generate([], "x", num_candidates=1)

    graph = state["graphs"][0]["prompt"]
    assert graph["4"]["class_type"] == "LoraLoaderModelOnly"
    assert graph["5"]["inputs"]["model"] == ["4", 0]
    assert graph["14"]["inputs"]["steps"] == 4
    assert graph["14"]["inputs"]["cfg"] == 1.0


def test_z_image_turbo_preset_is_text_only() -> None:
    handler, state = _server(
        outputs={
            "9": {"images": [{"filename": "z.png", "subfolder": "", "type": "output"}]}
        }
    )
    generator = _generator(handler, preset="z_image_turbo")

    generator.generate([_material("棉")], "x", num_candidates=1)

    assert state["uploads"] == []  # 文生图预设忽略参考图
    graph = state["graphs"][0]["prompt"]
    assert graph["2"]["inputs"]["type"] == "z_image"
    assert graph["7"]["inputs"]["steps"] == 8
    assert graph["7"]["inputs"]["cfg"] == 1.0
    assert "LoadImage" not in {node["class_type"] for node in graph.values()}


# --------------------------------------------------------------------------- #
# 自定义工作流
# --------------------------------------------------------------------------- #
def test_custom_preset_injects_into_user_graph() -> None:
    handler, state = _server(
        outputs={
            "8": {"images": [{"filename": "u.png", "subfolder": "", "type": "output"}]}
        }
    )
    generator = _generator(
        handler,
        preset="custom",
        workflow_json=_custom_workflow_json(),
        steps=12,
        cfg=3.0,
    )

    generator.generate(
        [_material("棉")], _DESIGN_IDEA, ReferenceImage(image_bytes=_png())
    )

    graph = state["graphs"][0]["prompt"]
    assert _DESIGN_IDEA in graph["2"]["inputs"]["text"]  # positive 由链接推断出来
    assert graph["3"]["inputs"]["text"] != "占位负向"  # negative 也被替换
    assert graph["4"]["inputs"]["image"] == "cloth_ref_abc.jpg"
    assert graph["5"]["inputs"]["width"] == 1024
    assert graph["5"]["inputs"]["height"] == 1024
    assert graph["6"]["inputs"]["seed"] == 12345
    assert graph["6"]["inputs"]["steps"] == 12
    assert graph["6"]["inputs"]["cfg"] == 3.0


def test_custom_preset_without_json_reports_config_error() -> None:
    handler, _state = _server()
    generator = _generator(handler, preset="custom", workflow_json="")

    with pytest.raises(ProviderError, match="自定义工作流"):
        generator.generate([], "x", num_candidates=1)


def test_unknown_preset_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="未知的 ComfyUI 预设"):
        _generator(lambda request: httpx.Response(200), preset="sd15")


def test_custom_workflow_missing_sampler_is_reported() -> None:
    problems = validate_custom_workflow(
        json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}})
    )
    assert any("KSampler" in problem for problem in problems)


def test_parse_workflow_rejects_non_api_format() -> None:
    with pytest.raises(ValueError, match="class_type"):
        parse_workflow(json.dumps({"1": {"inputs": {}}}))


def test_align_to_latent() -> None:
    assert align_to_latent(1024) == 1024
    assert align_to_latent(1003) == 992
    assert align_to_latent(4) == 16


# --------------------------------------------------------------------------- #
# 失败路径
# --------------------------------------------------------------------------- #
def test_node_errors_surface_readable_reason() -> None:
    handler, _state = _server(
        prompt_status=400,
        prompt_response={
            "error": {
                "type": "invalid_prompt",
                "message": "Cannot execute because a node is missing",
            },
            "node_errors": {
                "1": {"errors": [{"message": "Value not in list: unet_name"}]}
            },
        },
    )
    generator = _generator(handler)

    with pytest.raises(ProviderBadRequestError) as info:
        generator.generate([], "x", num_candidates=1)
    assert "unet_name" in str(info.value)


def test_transient_poll_failure_does_not_abort_queued_job() -> None:
    """已排队的任务不会因一次网络抖动被误判失败（重发反而会变成两次生成）。"""
    handler, state = _server(history_failures=2, history_calls_before_done=0)
    generator = _generator(handler)

    results = generator.generate([], "x", num_candidates=1)

    assert results[0].image_bytes
    assert state["history_calls"] == 3  # 2 次 503 + 1 次成功


def test_execution_error_is_raised_with_node_detail() -> None:
    handler, _state = _server(
        status={
            "status_str": "error",
            "completed": False,
            "messages": [
                [
                    "execution_error",
                    {"node_type": "KSampler", "exception_message": "OOM"},
                ]
            ],
        }
    )
    generator = _generator(handler)

    with pytest.raises(ProviderError) as info:
        generator.generate([], "x", num_candidates=1)
    assert "KSampler" in str(info.value)
    assert "OOM" in str(info.value)


def test_completed_without_images_is_an_error() -> None:
    handler, _state = _server(outputs={"16": {"images": []}})
    generator = _generator(handler)

    with pytest.raises(ProviderError, match="没有输出图片"):
        generator.generate([], "x", num_candidates=1)


def test_upload_failure_is_not_retried_forever() -> None:
    handler, _state = _server(fail_uploads=True)
    generator = _generator(handler)

    with pytest.raises(ProviderError):
        generator.generate([], _DESIGN_IDEA, ReferenceImage(image_bytes=_png()))


def test_system_stats_unreachable_is_reported_by_check_setup() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    problems = _generator(handler).check_setup()
    assert any("无法连接" in problem for problem in problems)


def test_check_setup_passes_when_models_exist() -> None:
    handler, _state = _server()
    assert _generator(handler).check_setup() == []


def test_check_setup_reports_missing_model_file() -> None:
    handler, _state = _server()
    generator = _generator(handler, model="not-on-disk.safetensors")

    problems = generator.check_setup()
    assert any("not-on-disk.safetensors" in problem for problem in problems)

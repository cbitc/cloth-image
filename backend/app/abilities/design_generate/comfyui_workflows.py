"""ComfyUI 工作流（API 格式）构建与参数注入。

ComfyUI 的「Save (API Format)」导出物是一张**扁平图**：

    {"3": {"class_type": "KSampler", "inputs": {...}}, "4": {...}}

其中链接写成 ``[node_id, output_index]``。本模块提供两件事：

1. 内置预设图（`build_qwen_image_edit` / `build_z_image_turbo`）：
   按「标准 Qwen-Image / Z-Image 资产」组装节点，参数化提示词、尺寸、seed 等。
   主模型（UNETLoader 的 unet_name）由设置页的 `design_generator_model` 覆盖，
   留空时用本模块顶部的默认文件名。
2. `inject_custom_workflow()`：往**用户自带**的工作流里注入参数。
   不要求用户标注任何东西，靠结构化推断：
     - 提示词 → 从 KSampler 的 positive / negative 输入沿链接向上找「文本节点」
     - 参考图 → 按 node id 升序依次填给 LoadImage
     - 尺寸   → 填给 Empty*LatentImage（若无则不动）
     - seed/步数/CFG → 填给 KSampler / KSamplerAdvanced
   因此自定义工作流至少要有一个采样器与一个输出节点（SaveImage / PreviewImage）。

注意：CLIP / VAE 的文件名在本模块里按标准资产硬编码
（`qwen_2.5_vl_7b_fp8_scaled` + `qwen_image_vae` / `qwen_3_4b` + `z_image_turbo-vae`）；
换了权重/量化版本时请改用 `custom` 预设粘自己的 JSON。
"""

from __future__ import annotations

import copy
import logging
import re
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 标准资产文件名（可被设置页 design_generator_model 覆盖主模型）
# --------------------------------------------------------------------------- #
QWEN_IMAGE_EDIT_UNET = "Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors"
QWEN_IMAGE_CLIP = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
QWEN_IMAGE_VAE = "qwen_image_vae.safetensors"
Z_IMAGE_UNET = "z_image_turbo_bf16.safetensors"
Z_IMAGE_CLIP = "qwen_3_4b.safetensors"
Z_IMAGE_VAE = "z_image_turbo-vae.safetensors"

#: 预设 → 主模型默认文件名（设置页留空时使用）
PRESET_DEFAULT_UNET: dict[str, str] = {
    "qwen_image_edit": QWEN_IMAGE_EDIT_UNET,
    "z_image_turbo": Z_IMAGE_UNET,
}

#: 预设 → 采样默认值 (steps, cfg, sampler, scheduler)
PRESET_SAMPLING: dict[str, tuple[int, float, str, str]] = {
    "qwen_image_edit": (20, 2.5, "euler", "simple"),
    "z_image_turbo": (8, 1.0, "euler", "simple"),
}

#: 挂了 Lightning 4 步 LoRA 时的推荐采样参数
LIGHTNING_SAMPLING = (4, 1.0)

PRESETS = ("qwen_image_edit", "z_image_turbo", "custom")

#: 潜变量尺寸必须对齐（SD3/Qwen 的 8x 下采样 + patch 2 → 16 的倍数）
_LATENT_ALIGN = 16

#: 文本节点里可能承载提示词的输入名（按优先级）
_PROMPT_KEYS = (
    "prompt",
    "text",
    "t5xxl",
    "clip_l",
    "clip_g",
    "text_g",
    "llama",
    "bert",
)

#: 可写尺寸的潜变量节点
_LATENT_CLASSES = {
    "EmptyLatentImage",
    "EmptySD3LatentImage",
    "EmptySDXLImage",
    "EmptyFlux2LatentImage",
    "EmptyChromaRadianceLatentImage",
}

#: 采样器：{class_type: (seed 字段, 是否有 steps/cfg)}
_SAMPLER_CLASSES = {
    "KSampler": "seed",
    "KSamplerAdvanced": "noise_seed",
}

#: 输出节点（按优先级取第一个能出图的）
_OUTPUT_CLASSES = (
    "SaveImage",
    "SaveImageAdvanced",
    "PreviewImage",
    "SaveAnimatedPNG",
    "SaveAnimatedWEBP",
)


def align_to_latent(value: int) -> int:
    """把边长对齐到潜变量网格（向下取整，至少 16）。"""
    return max(_LATENT_ALIGN, int(value) // _LATENT_ALIGN * _LATENT_ALIGN)


# --------------------------------------------------------------------------- #
# 内置预设
# --------------------------------------------------------------------------- #
def build_qwen_image_edit(
    *,
    prompt: str,
    negative_prompt: str,
    reference_names: list[str],
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    unet: str = "",
    lora: str = "",
    lora_strength: float = 1.0,
    sampler: str = "euler",
    scheduler: str = "simple",
    filename_prefix: str = "cloth-design",
) -> dict[str, Any]:
    """Qwen-Image-Edit（图生图）：参考图 → VAEEncode 作 latent，参考图进 conditioning。

    有参考图时 latent 取自**参考图本身**（编辑语义：保留版型/构图、按提示词改）；
    没有参考图时退化为纯文生图（空 latent）。
    """
    width, height = align_to_latent(width), align_to_latent(height)

    graph: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": unet or QWEN_IMAGE_EDIT_UNET,
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": QWEN_IMAGE_CLIP, "type": "qwen_image"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": QWEN_IMAGE_VAE}},
    }

    model_ref: list[Any] = ["1", 0]
    if lora:
        graph["4"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": lora,
                "strength_model": lora_strength,
            },
        }
        model_ref = ["4", 0]

    graph["5"] = {
        "class_type": "ModelSamplingAuraFlow",
        "inputs": {"model": model_ref, "shift": 3.1},
    }
    model_ref = ["5", 0]

    # 参考图：LoadImage 依序编号，image1..image3 最多三张（模型上限）
    image_refs: list[list[Any]] = []
    for index, name in enumerate(reference_names[:3]):
        node_id = str(20 + index)
        graph[node_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        image_refs.append([node_id, 0])

    positive_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "prompt": prompt,
        "vae": ["3", 0],
    }
    negative_inputs: dict[str, Any] = {
        "clip": ["2", 0],
        "prompt": negative_prompt,
        "vae": ["3", 0],
    }
    for index, ref in enumerate(image_refs):
        positive_inputs[f"image{index + 1}"] = ref
        negative_inputs[f"image{index + 1}"] = ref

    graph["10"] = {
        "class_type": "TextEncodeQwenImageEditPlus",
        "inputs": positive_inputs,
    }
    graph["11"] = {
        "class_type": "TextEncodeQwenImageEditPlus",
        "inputs": negative_inputs,
    }

    if image_refs:
        graph["12"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": image_refs[0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "disabled",
            },
        }
        graph["13"] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["12", 0], "vae": ["3", 0]},
        }
    else:
        graph["13"] = {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        }

    graph["14"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": scheduler,
            "denoise": 1.0,
            "positive": ["10", 0],
            "negative": ["11", 0],
            "latent_image": ["13", 0],
        },
    }
    graph["15"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["14", 0], "vae": ["3", 0]},
    }
    graph["16"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["15", 0], "filename_prefix": filename_prefix},
    }
    return graph


def build_z_image_turbo(
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    unet: str = "",
    sampler: str = "euler",
    scheduler: str = "simple",
    filename_prefix: str = "cloth-design",
) -> dict[str, Any]:
    """Z-Image-Turbo（纯文生图）：忽略参考图，只吃提示词，8 步出图。"""
    width, height = align_to_latent(width), align_to_latent(height)

    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": unet or Z_IMAGE_UNET, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": Z_IMAGE_CLIP, "type": "z_image"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": Z_IMAGE_VAE}},
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": prompt},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": negative_prompt},
        },
        "6": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1.0,
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix},
        },
    }


# --------------------------------------------------------------------------- #
# 自定义工作流：结构化注入
# --------------------------------------------------------------------------- #
def parse_workflow(workflow_json: str) -> dict[str, Any]:
    """解析「Save (API Format)」导出的 JSON。失败抛 ValueError（带可读原因）。"""
    import json

    text = (workflow_json or "").strip()
    if not text:
        raise ValueError(
            "自定义工作流为空：请粘贴 ComfyUI「Save (API Format)」导出的 JSON"
        )
    try:
        graph = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"自定义工作流不是合法 JSON：{exc}") from exc
    if isinstance(graph, dict) and isinstance(graph.get("prompt"), dict):
        # 容忍整包 UI 导出（{"prompt": {...}}）时取内层图
        graph = graph["prompt"]
    if not isinstance(graph, dict) or not graph:
        raise ValueError("自定义工作流应为 {节点ID: {class_type, inputs}} 形式的对象")
    for node_id, node in graph.items():
        if not isinstance(node, dict) or "class_type" not in node:
            raise ValueError(f"节点 {node_id} 缺少 class_type，可能不是 API 格式导出")
    return graph


def _node_ids(graph: dict[str, Any], classes: set[str] | tuple[str, ...]) -> list[str]:
    wanted = set(classes)
    return sorted(
        (
            node_id
            for node_id, node in graph.items()
            if node.get("class_type") in wanted
        ),
        key=_node_sort_key,
    )


def _node_sort_key(node_id: str) -> tuple[int, str]:
    """node id 通常是数字字符串；保证 '9' 排在 '10' 前面（上传顺序才稳定）。"""
    return (
        (int(node_id), node_id) if str(node_id).isdigit() else (1 << 30, str(node_id))
    )


def _link_target(value: Any) -> str | None:
    """把 ``[node_id, output_index]`` 链接解析成 node_id。"""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (str, int)):
        return str(value[0])
    return None


def _find_prompt_node(
    graph: dict[str, Any], start: Any, *, depth: int = 8
) -> tuple[str, str] | None:
    """从某个 conditioning 输入沿链接向上找承载提示词的节点。

    返回 (node_id, 字段名)；找不到返回 None。用 BFS，深度受限避免环形图打转。
    """
    root = _link_target(start)
    if root is None:
        return None

    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root, 0)])
    while queue:
        node_id, level = queue.popleft()
        if node_id in seen or level > depth:
            continue
        seen.add(node_id)

        node = graph.get(node_id)
        if not isinstance(node, dict):
            continue

        inputs = node.get("inputs") or {}
        for key in _PROMPT_KEYS:
            if isinstance(inputs.get(key), str):
                return node_id, key

        if level == depth:
            continue
        for value in inputs.values():
            target = _link_target(value)
            if target is not None:
                queue.append((target, level + 1))

    return None


def custom_workflow_output_nodes(graph: dict[str, Any]) -> list[str]:
    """自定义工作流的出图节点（按优先级排序）。"""
    found: list[str] = []
    for class_type in _OUTPUT_CLASSES:
        found.extend(_node_ids(graph, {class_type}))
    return found


def inject_custom_workflow(
    graph: dict[str, Any],
    *,
    prompt: str,
    negative_prompt: str,
    reference_names: list[str],
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
) -> tuple[dict[str, Any], list[str]]:
    """把参数注入自定义工作流，返回 (新图, 出图节点 id 列表)。

    结构化推断，不需要用户做任何标注。至少需要一个 KSampler 与一个输出节点。
    """
    graph = copy.deepcopy(graph)
    width, height = align_to_latent(width), align_to_latent(height)

    samplers = _node_ids(graph, set(_SAMPLER_CLASSES))
    if not samplers:
        raise ValueError("自定义工作流里找不到 KSampler / KSamplerAdvanced 节点")

    # 1) 提示词：主采样器的 positive / negative 各向上找一次
    primary = graph[samplers[0]].get("inputs") or {}
    for key, text in (("positive", prompt), ("negative", negative_prompt)):
        if key not in primary:
            continue
        target = _find_prompt_node(graph, primary[key])
        if target is None:
            logger.warning("自定义工作流：未能定位 %s 提示词节点，跳过注入", key)
            continue
        node_id, field = target
        graph[node_id]["inputs"][field] = text

    # 2) 参考图：LoadImage 按 node id 升序依次填充
    loads = _node_ids(graph, ("LoadImage",))
    for node_id, name in zip(loads, reference_names[:3]):
        graph[node_id]["inputs"]["image"] = name

    # 3) 尺寸：只改空 latent（编辑类工作流的 latent 来自 VAEEncode，不能动）
    for node_id in _node_ids(graph, _LATENT_CLASSES):
        inputs = graph[node_id]["inputs"]
        if "width" in inputs:
            inputs["width"] = width
        if "height" in inputs:
            inputs["height"] = height

    # 4) 采样参数
    for node_id in samplers:
        inputs = graph[node_id]["inputs"]
        seed_field = _SAMPLER_CLASSES.get(graph[node_id]["class_type"])
        if seed_field and seed_field in inputs:
            inputs[seed_field] = seed
        if "steps" in inputs:
            inputs["steps"] = steps
        if "cfg" in inputs:
            inputs["cfg"] = cfg

    # 5) 出图节点
    outputs = custom_workflow_output_nodes(graph)
    if not outputs:
        raise ValueError(
            "自定义工作流里找不到输出节点（需要 SaveImage 或 PreviewImage）"
        )

    return graph, outputs


def validate_custom_workflow(workflow_json: str) -> list[str]:
    """静态校验自定义工作流，返回问题清单（空 = OK）。不联网。"""
    problems: list[str] = []
    try:
        graph = parse_workflow(workflow_json)
    except ValueError as exc:
        return [str(exc)]

    try:
        inject_custom_workflow(
            graph,
            prompt="probe",
            negative_prompt="probe",
            reference_names=[],
            width=1024,
            height=1024,
            seed=1,
            steps=1,
            cfg=1.0,
        )
    except ValueError as exc:
        problems.append(str(exc))

    if not _node_ids(graph, ("LoadImage",)):
        problems.append("工作流里没有 LoadImage 节点：参考图/材质图不会被使用")
    return problems


_SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


def parse_size(size: str) -> tuple[int, int]:
    """把 `"1024x1024"` 解析成 (宽, 高)。"""
    match = _SIZE_RE.match((size or "").strip())
    if not match:
        raise ValueError(
            f"image_size 必须形如 '1024x1024'（用 x 分隔），收到: {size!r}"
        )
    return int(match.group(1)), int(match.group(2))

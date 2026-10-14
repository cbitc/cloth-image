"""可配置项清单与校验。

前端设置页根据这里的 spec 动态渲染表单，因此**增删配置项只需改这一处**。

安全约定：
- `secret=True` 的字段永远不会把值返回给前端，只返回 `configured: bool`
- 写入时：值为 `None` → 删除覆盖（回退到环境变量）；`""` → 显式置空；其它 → 覆盖
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# 四个能力的元信息（用于展示状态、校验 provider 名）
# --------------------------------------------------------------------------- #
ABILITY_SPECS: list[dict[str, Any]] = [
    {
        "ability": "clothing_search",
        "label": "搜索服装图",
        "signature": "[网站列表] → [服装图片列表]",
        "options": ["mock", "serpapi"],
        "stub_options": ["serpapi"],
        "key_field": {"serpapi": "serpapi_api_key"},
        "option_hint": {"serpapi": "需要 SERPAPI_API_KEY，实现仍是占位"},
    },
    {
        "ability": "material_identifier",
        "label": "识别服装材质",
        "signature": "服装图片 → [材质 tag 列表]",
        "options": ["mock", "maas"],
        "stub_options": [],
        "key_field": {"maas": "resolved_vlm_api_key"},
        "option_hint": {"maas": "调用阿里云 MaaS 的视觉语言模型"},
    },
    {
        "ability": "material_search",
        "label": "查找材质图",
        "signature": "[材质 tag 列表] → [材质图片列表]",
        "options": ["mock", "serpapi"],
        "stub_options": ["serpapi"],
        "key_field": {"serpapi": "serpapi_api_key"},
        "option_hint": {"serpapi": "需要 SERPAPI_API_KEY，实现仍是占位"},
    },
    {
        "ability": "design_generator",
        "label": "图生图生成设计图",
        "signature": "([材质图片], 设计想法) → [设计图]",
        "options": ["mock", "dashscope", "fal"],
        "stub_options": ["fal"],
        "key_field": {"dashscope": "resolved_image_api_key", "fal": "fal_key"},
        "option_hint": {"dashscope": "调用阿里云 MaaS 的 qwen-image 系列"},
    },
]

# --------------------------------------------------------------------------- #
# 可编辑字段
# --------------------------------------------------------------------------- #
# 四个能力的 provider 选择项由 ABILITY_SPECS 自动生成，避免两处维护。
# choices 里的空串表示「跟随全局兜底模式」。
_PROVIDER_FIELDS: list[dict[str, Any]] = [
    {
        "name": f"{spec['ability']}_provider",
        "label": spec["label"],
        "group": "能力提供方",
        "type": "select",
        "choices": ["", *spec["options"]],
        "option_labels": {"": "跟随全局模式", **spec.get("option_labels", {})},
        "help": spec["signature"],
    }
    for spec in ABILITY_SPECS
]

# type: select | text | secret | int | float | bool
FIELD_SPECS: list[dict[str, Any]] = [
    {
        "name": "provider_mode",
        "label": "全局兜底模式",
        "group": "能力提供方",
        "type": "select",
        "choices": ["mock", "real"],
        "help": "单项能力留空时回退到这里。mock = 假数据，零外部依赖。",
    },
    *_PROVIDER_FIELDS,
    {
        "name": "maas_base_url",
        "label": "MaaS 端点 Base URL",
        "group": "阿里云 MaaS",
        "type": "text",
        "help": "OpenAI 兼容地址，识别与生图共用。",
    },
    {
        "name": "maas_api_key",
        "label": "MaaS API Key",
        "group": "阿里云 MaaS",
        "type": "secret",
        "help": "留空表示不修改；点「清除」则回退到环境变量。",
    },
    {
        "name": "vlm_model",
        "label": "视觉识别模型",
        "group": "阿里云 MaaS",
        "type": "text",
        "help": "需为视觉语言模型，例如 qwen3-vl-plus。",
    },
    {
        "name": "image_model",
        "label": "生图模型",
        "group": "阿里云 MaaS",
        "type": "text",
        "help": "例如 qwen-image-3.0。",
    },
    {
        "name": "image_size",
        "label": "生图尺寸",
        "group": "阿里云 MaaS",
        "type": "text",
        "pattern": r"^\d+x\d+$",
        "help": "必须用 x 分隔，形如 1024x1024；写成 1024*1024 会被接口拒绝。",
    },
    {
        "name": "image_max_refs",
        "label": "参考图上限",
        "group": "阿里云 MaaS",
        "type": "int",
        "min": 0,
        "max": 3,
        "help": "实测 qwen-image-3.0 只支持 0~3 张（0 = 纯文生图）。",
    },
    {
        "name": "prompt_extend",
        "label": "允许模型改写提示词",
        "group": "阿里云 MaaS",
        "type": "bool",
        "help": "提示词已结构化组装，一般建议关闭。",
    },
    {
        "name": "vlm_api_key",
        "label": "识别专用 Key",
        "group": "MaaS 细分覆盖",
        "type": "secret",
        "help": "留空则复用 MaaS API Key。",
    },
    {
        "name": "image_api_key",
        "label": "生图专用 Key",
        "group": "MaaS 细分覆盖",
        "type": "secret",
        "help": "留空则复用 MaaS API Key。",
    },
    {
        "name": "vlm_base_url",
        "label": "识别专用 Base URL",
        "group": "MaaS 细分覆盖",
        "type": "text",
        "help": "留空则复用 MaaS 端点。",
    },
    {
        "name": "image_base_url",
        "label": "生图专用 Base URL",
        "group": "MaaS 细分覆盖",
        "type": "text",
        "help": "留空则复用 MaaS 端点。",
    },
    {
        "name": "serpapi_api_key",
        "label": "SerpAPI Key",
        "group": "其他提供方",
        "type": "secret",
        "help": "搜图 / 材质图检索用（对应实现仍是占位）。",
    },
    {
        "name": "fal_key",
        "label": "fal.ai Key",
        "group": "其他提供方",
        "type": "secret",
        "help": "备选生图提供方（实现仍是占位）。",
    },
    {
        "name": "identify_top_k",
        "label": "最多输出几个材质候选",
        "group": "流水线参数",
        "type": "int",
        "min": 1,
        "max": 8,
    },
    {
        "name": "material_images_per_tag",
        "label": "每个 tag 检索几张面料图",
        "group": "流水线参数",
        "type": "int",
        "min": 1,
        "max": 8,
    },
    {
        "name": "design_candidates",
        "label": "默认生成几张设计图",
        "group": "流水线参数",
        "type": "int",
        "min": 1,
        "max": 6,
    },
    {
        "name": "identify_cache_enabled",
        "label": "启用识别结果缓存",
        "group": "流水线参数",
        "type": "bool",
        "help": "相同图片 + 相同模型时跳过模型调用，单次可省约 1500 tokens。",
    },
    {
        "name": "provider_timeout_s",
        "label": "外部调用超时（秒）",
        "group": "HTTP 与图片",
        "type": "float",
        "min": 5,
        "max": 600,
    },
    {
        "name": "provider_max_retries",
        "label": "失败重试次数",
        "group": "HTTP 与图片",
        "type": "int",
        "min": 0,
        "max": 8,
    },
    {
        "name": "vision_max_image_side",
        "label": "送模型前图片最长边",
        "group": "HTTP 与图片",
        "type": "int",
        "min": 256,
        "max": 4096,
        "help": "等比缩放上限，越大越清晰但 token 成本越高。",
    },
]

_FIELDS_BY_NAME: dict[str, dict[str, Any]] = {
    spec["name"]: spec for spec in FIELD_SPECS
}

EDITABLE_FIELD_NAMES: tuple[str, ...] = tuple(spec["name"] for spec in FIELD_SPECS)

SECRET_FIELD_NAMES: tuple[str, ...] = tuple(
    spec["name"] for spec in FIELD_SPECS if spec.get("type") == "secret"
)


class SettingsValidationError(ValueError):
    """字段名未知或取值非法。"""


def is_editable(name: str) -> bool:
    return name in _FIELDS_BY_NAME


def coerce(name: str, raw: Any) -> Any:
    """按 spec 校验并转换单个值。非法时抛 SettingsValidationError。"""
    spec = _FIELDS_BY_NAME.get(name)
    if spec is None:
        raise SettingsValidationError(f"不可配置的项：{name}")

    kind = spec["type"]

    if kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip().lower() in {"true", "false", "1", "0"}:
            return raw.strip().lower() in {"true", "1"}
        if isinstance(raw, int) and raw in (0, 1):
            return bool(raw)
        raise SettingsValidationError(f"{spec['label']} 需要布尔值")

    if kind in {"int", "float"}:
        try:
            number = int(raw) if kind == "int" else float(raw)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError(f"{spec['label']} 需要数字") from exc
        if "min" in spec and number < spec["min"]:
            raise SettingsValidationError(f"{spec['label']} 不能小于 {spec['min']}")
        if "max" in spec and number > spec["max"]:
            raise SettingsValidationError(f"{spec['label']} 不能大于 {spec['max']}")
        return number

    text = str(raw).strip()

    if kind == "select":
        if text not in spec["choices"]:
            raise SettingsValidationError(
                f"{spec['label']} 只能是：{', '.join(spec['choices'])}"
            )
        return text

    pattern = spec.get("pattern")
    if pattern:
        import re

        if not re.match(pattern, text):
            raise SettingsValidationError(f"{spec['label']} 格式不符：{text!r}")
    return text


def validate_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """校验整个提交体。`None` 表示删除覆盖，原样保留。"""
    cleaned: dict[str, Any] = {}
    for name, raw in patch.items():
        if raw is None:
            cleaned[name] = None
            continue
        cleaned[name] = coerce(name, raw)
    return cleaned

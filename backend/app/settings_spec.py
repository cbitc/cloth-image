"""可配置项清单与校验。

前端设置页根据这里的 spec 动态渲染表单，因此**增删配置项只需改这一处**。

两类字段（重构后职责分离）：
- **能力配置**（由 `ABILITY_SPECS` 生成）：设置页写入数据库，是**唯一来源**，不读环境变量。
- **环境变量字段**：环境变量 / .env 提供默认值，设置页可覆盖。

安全约定：
- `secret=True` 的字段永远不会把值返回给前端，只返回 `configured: bool`
- 写入时：值为 `None` → 删除覆盖（回退到默认值 / 环境变量）；`""` → 显式置空；其它 → 覆盖
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# 四个能力的元信息
# --------------------------------------------------------------------------- #
# `real_implemented=False` 的能力只有 mock 实现：UI 只展示状态，不提供 provider 选择。
# provider 按协议命名（不绑定厂商）：
#   material_identifier : openai_compatible        （OpenAI 兼容 /chat/completions）
#   design_generator    : openai_compatible_image  （OpenAI 兼容 /images/generations）
ABILITY_SPECS: list[dict[str, Any]] = [
    {
        "ability": "clothing_search",
        "label": "搜索服装图",
        "signature": "[网站列表] → [服装图片列表]",
        "real_implemented": False,
        "options": ["mock"],
        "hint": "暂无真实实现，仅供演示",
        "fields": [],
    },
    {
        "ability": "material_identifier",
        "label": "识别服装材质",
        "signature": "服装图片 → [材质 tag 列表]",
        "real_implemented": True,
        "options": ["mock", "openai_compatible"],
        "hint": "底层走 OpenAI 兼容协议（/chat/completions），可指向任意兼容端点",
        "fields": [
            {
                "name": "material_identifier_base_url",
                "label": "端点 Base URL",
                "type": "text",
                "placeholder": "https://<your-endpoint>/v1",
                "help": "只写到此为止，不含 /chat/completions。",
            },
            {
                "name": "material_identifier_api_key",
                "label": "API Key",
                "type": "secret",
            },
            {
                "name": "material_identifier_model",
                "label": "视觉语言模型",
                "type": "text",
                "placeholder": "例如 qwen3-vl-plus / gpt-4o",
            },
        ],
    },
    {
        "ability": "material_search",
        "label": "查找材质图",
        "signature": "[材质 tag 列表] → [材质图片列表]",
        "real_implemented": False,
        "options": ["mock"],
        "hint": "暂无真实实现，仅供演示",
        "fields": [],
    },
    {
        "ability": "design_generator",
        "label": "图生图生成设计图",
        "signature": "([材质图片], 设计想法) → [设计图]",
        "real_implemented": True,
        "options": ["mock", "openai_compatible_image"],
        "hint": "底层走 OpenAI 兼容协议（/images/generations），可指向任意兼容端点",
        "fields": [
            {
                "name": "design_generator_base_url",
                "label": "端点 Base URL",
                "type": "text",
                "placeholder": "https://<your-endpoint>/v1",
                "help": "只写到此为止，不含 /images/generations。",
            },
            {
                "name": "design_generator_api_key",
                "label": "API Key",
                "type": "secret",
            },
            {
                "name": "design_generator_model",
                "label": "生图模型",
                "type": "text",
                "placeholder": "例如 qwen-image-3.0",
            },
        ],
    },
]

# --------------------------------------------------------------------------- #
# 可编辑字段
# --------------------------------------------------------------------------- #
# 能力配置字段由 ABILITY_SPECS 自动生成，避免两处维护。
_REAL_OPTIONS: dict[str, list[str]] = {
    spec["ability"]: [opt for opt in spec["options"] if opt != "mock"]
    for spec in ABILITY_SPECS
}


def _provider_fields() -> list[dict[str, Any]]:
    """每个「有真实实现」的能力一个 provider 选择框（无空值、无全局回退）。"""
    return [
        {
            "name": f"{spec['ability']}_provider",
            "label": "实现",
            "group": "能力配置",
            "type": "select",
            "choices": spec["options"],
            "help": spec["signature"],
        }
        for spec in ABILITY_SPECS
        if spec["real_implemented"]
    ]


def _provider_specific_fields() -> list[dict[str, Any]]:
    """provider 专属字段：仅当该能力选中真实实现时显示（`show_when`）。"""
    out: list[dict[str, Any]] = []
    for spec in ABILITY_SPECS:
        real = _REAL_OPTIONS[spec["ability"]]
        for field in spec["fields"]:
            merged = {"group": "能力配置", **field}
            if real:
                merged["show_when"] = {f"{spec['ability']}_provider": real}
            out.append(merged)
    return out


_PROVIDER_FIELDS = _provider_fields()
_PROVIDER_SPECIFIC_FIELDS = _provider_specific_fields()

#: 能力配置字段名（DB 为唯一来源，不读环境变量）
ABILITY_FIELD_NAMES: tuple[str, ...] = tuple(
    spec["name"] for spec in [*_PROVIDER_FIELDS, *_PROVIDER_SPECIFIC_FIELDS]
)

# type: select | text | secret | int | float | bool
FIELD_SPECS: list[dict[str, Any]] = [
    *_PROVIDER_FIELDS,
    *_PROVIDER_SPECIFIC_FIELDS,
    {
        "name": "identify_top_k",
        "label": "最多输出几个材质候选",
        "group": "识别参数",
        "type": "int",
        "min": 1,
        "max": 8,
    },
    {
        "name": "vision_max_image_side",
        "label": "送模型前图片最长边",
        "group": "识别参数",
        "type": "int",
        "min": 256,
        "max": 4096,
        "help": "等比缩放上限，越大越清晰但 token 成本越高。",
    },
    {
        "name": "image_size",
        "label": "生图尺寸",
        "group": "生图参数",
        "type": "text",
        "pattern": r"^\d+x\d+$",
        "help": "必须用 x 分隔，形如 1024x1024；写成 1024*1024 会被接口拒绝。",
    },
    {
        "name": "image_max_refs",
        "label": "参考图上限",
        "group": "生图参数",
        "type": "int",
        "min": 0,
        "max": 3,
        "help": "实测 qwen-image-3.0 只支持 0~3 张（0 = 纯文生图）。",
    },
    {
        "name": "prompt_extend",
        "label": "允许模型改写提示词",
        "group": "生图参数",
        "type": "bool",
        "help": "提示词已结构化组装，一般建议关闭。",
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
        "group": "HTTP 与重试",
        "type": "float",
        "min": 5,
        "max": 600,
    },
    {
        "name": "provider_max_retries",
        "label": "失败重试次数",
        "group": "HTTP 与重试",
        "type": "int",
        "min": 0,
        "max": 8,
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

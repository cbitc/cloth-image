"""材质卡片的归一化与序列化。

模型（VLM）返回的 JSON 不可信：枚举值可能写成近义词、色值可能缺 `#`、
色板占比可能不归零、置信度可能超出 0~1。所有清洗集中在这里，
让 provider 只负责「发请求 + 取文本」，也让测试可以脱离 HTTP 直接验证规则。

同时提供卡片 ↔ 可 JSON 化字典的双向转换（DB `payload` 列与识别缓存共用）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.abilities.base import (
    BehaviorInfo,
    ColorInfo,
    FabricInfo,
    MaterialCardResult,
    MaterialRegionResult,
    OpticalInfo,
    PatternInfo,
    RegionConfidence,
)
from app.abilities.image_ops import (
    DEFAULT_SWATCH_MAX_SIDE,
    crop_normalized,
    normalize_box,
)
from app.taxonomy import (
    CATEGORY_OPTIONS,
    DEFAULT_CATEGORY,
    DEFAULT_DRAPE,
    DEFAULT_GLOSS,
    DEFAULT_PATTERN_TYPE,
    DEFAULT_TRANSPARENCY,
    DEFAULT_WEIGHT,
    DRAPE_LEVELS,
    GLOSS_LEVELS,
    PATTERN_TYPES,
    TRANSPARENCY_LEVELS,
    WEIGHT_LEVELS,
    match_material,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")
#: 模型常用英文/缩写 → 受控中文取值
_ALIASES: dict[str, tuple[str, ...]] = {
    "纯色": ("solid", "plain", "self-colored", "single color"),
    "条纹": ("stripe", "striped", "pinstripe"),
    "格纹": ("plaid", "check", "checked", "gingham", "tartan"),
    "碎花": ("floral", "flower", "small print"),
    "定位印花": ("placement", "engineered print", "placement print"),
    "哑光": ("matte", "matt", "dull", "flat"),
    "微光": ("slight sheen", "soft sheen", "low gloss", "semi-gloss", "glossy"),
    "缎面": ("satin", "silky sheen", "satin finish"),
    "金属光": ("metallic", "metallic sheen", "foil"),
    "不透明": ("opaque",),
    "半透明": ("semi-transparent", "semi transparent", "translucent"),
    "透明": ("transparent", "sheer", "see-through"),
    "轻薄": ("light", "lightweight", "thin"),
    "中等": ("medium", "mid", "moderate"),
    "厚重": ("heavy", "heavyweight", "thick"),
    "挺括": ("stiff", "structured", "crisp"),
    "适中": ("balanced", "moderate", "medium"),
    "垂坠": ("draped", "drapey", "fluid", "flowy"),
    "女装上衣": ("top", "blouse", "women's top", "shirt"),
    "连衣裙": ("dress", "one-piece dress", "gown"),
}


def clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def normalize_hex(value: Any) -> str:
    """把模型给的颜色值规范成 `#RRGGBB`；无法识别时返回空串。"""
    if not isinstance(value, str):
        return ""
    match = _HEX_RE.match(value.strip())
    if not match:
        return ""
    return "#" + match.group(1).upper()


def normalize_lab(value: Any) -> tuple[float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        return tuple(round(float(component), 2) for component in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def normalize_palette(value: Any, *, limit: int = 6) -> list[dict[str, Any]]:
    """清洗色板并归一化占比（和 = 1、按占比降序、最多 `limit` 项）。"""
    if not isinstance(value, list):
        return []

    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        hex_value = normalize_hex(item.get("hex") or item.get("color"))
        if not hex_value:
            continue
        try:
            ratio = max(0.0, float(item.get("ratio", 0.0)))
        except (TypeError, ValueError):
            ratio = 0.0
        entries.append({"hex": hex_value, "ratio": ratio})

    if not entries:
        return []

    total = sum(entry["ratio"] for entry in entries)
    if total <= 0:
        # 模型没给占比：均分，至少保证 UI 能渲染
        evenly = round(1.0 / len(entries), 4)
        for entry in entries:
            entry["ratio"] = evenly
    else:
        for entry in entries:
            entry["ratio"] = round(entry["ratio"] / total, 4)

    entries.sort(key=lambda entry: entry["ratio"], reverse=True)
    return entries[:limit]


def pick_option(value: Any, allowed: tuple[str, ...], default: str) -> str:
    """把模型给的取值模糊对齐到受控枚举；无法对齐时返回 `default`。"""
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text:
        return default
    if text in allowed:
        return text

    lowered = text.lower()
    for option in allowed:
        if option in text:
            return option
    for option in allowed:
        if any(alias in lowered for alias in _ALIASES.get(option, ())):
            return option
    return default


def _field(raw: dict[str, Any], *names: str) -> Any:
    for name in names:
        if raw.get(name) not in (None, ""):
            return raw[name]
    return None


def normalize_color(raw: Any) -> ColorInfo:
    raw = raw if isinstance(raw, dict) else {}
    dominant = raw.get("dominant")
    dominant = dominant if isinstance(dominant, dict) else raw

    return ColorInfo(
        # `dominant_hex` 是我们自己 payload 的 key（模型侧一般用 `hex`）
        dominant_hex=normalize_hex(
            _field(dominant, "hex", "dominant_hex", "color", "value")
        ),
        dominant_name=str(
            _field(dominant, "name", "dominant_name", "name_zh", "label") or ""
        ).strip(),
        lab=normalize_lab(_field(dominant, "lab", "lab_value")),
        palette=normalize_palette(raw.get("palette")),
        distribution=str(raw.get("distribution") or "").strip(),
    )


def normalize_pattern(raw: Any) -> PatternInfo:
    raw = raw if isinstance(raw, dict) else {}
    return PatternInfo(
        type=pick_option(raw.get("type"), PATTERN_TYPES, DEFAULT_PATTERN_TYPE),
        scale=str(raw.get("scale") or "").strip(),
        direction=str(raw.get("direction") or "").strip(),
        layout=str(raw.get("layout") or "").strip(),
    )


def normalize_optical(raw: Any) -> OpticalInfo:
    raw = raw if isinstance(raw, dict) else {}
    return OpticalInfo(
        gloss=pick_option(raw.get("gloss"), GLOSS_LEVELS, DEFAULT_GLOSS),
        transparency=pick_option(
            raw.get("transparency"), TRANSPARENCY_LEVELS, DEFAULT_TRANSPARENCY
        ),
    )


def normalize_fabric(raw: Any, *, fallback_material: str = "") -> FabricInfo:
    """B 层。`material` 归一化回受控词表（词表外的名字原样保留并告警）。"""
    raw = raw if isinstance(raw, dict) else {}
    name = str(
        _field(raw, "material", "material_zh", "name") or fallback_material
    ).strip()
    material_en = str(_field(raw, "material_en", "material_en_name") or "").strip()

    definition = match_material(name, material_en)
    if name and definition is None:
        logger.warning("材质名不在受控词表内，原样保留: %r", name)

    return FabricInfo(
        material=definition["material"] if definition else name,
        material_en=(definition or {}).get("material_en", "") or material_en,
        category=str(
            _field(raw, "category") or (definition or {}).get("category", "")
        ).strip(),
        finish=str(raw.get("finish") or "").strip(),
        confidence=clamp_confidence(raw.get("confidence")),
    )


def normalize_behavior(raw: Any) -> BehaviorInfo:
    """C 层。MVP 期不做推断：模型没给就填默认值，并标记 `is_default`。"""
    raw = raw if isinstance(raw, dict) else {}
    provided = bool(raw.get("weight") or raw.get("drape"))
    return BehaviorInfo(
        weight=pick_option(raw.get("weight"), WEIGHT_LEVELS, DEFAULT_WEIGHT),
        drape=pick_option(raw.get("drape"), DRAPE_LEVELS, DEFAULT_DRAPE),
        confidence=clamp_confidence(raw.get("confidence")),
        is_default=not provided,
    )


def normalize_region_confidence(raw: Any) -> RegionConfidence:
    raw = raw if isinstance(raw, dict) else {}
    return RegionConfidence(
        color=clamp_confidence(raw.get("color")),
        pattern=clamp_confidence(raw.get("pattern")),
        gloss=clamp_confidence(raw.get("gloss")),
    )


def normalize_region(raw: Any, *, index: int = 0) -> MaterialRegionResult:
    raw = raw if isinstance(raw, dict) else {}

    fabric_raw = raw.get("fabric")
    fabric_raw = dict(fabric_raw) if isinstance(fabric_raw, dict) else {}
    # 旧格式兜底：区域/顶层直接给 `material`（字符串，或 {material: {...}} 包装）
    legacy = raw.get("material")
    if isinstance(legacy, dict):
        fabric_raw = {**legacy, **fabric_raw}
    elif isinstance(legacy, str) and legacy.strip():
        fabric_raw = {**fabric_raw, "material": legacy}

    return MaterialRegionResult(
        region_id=str(
            raw.get("region_id") or ("body" if index == 0 else f"region{index}")
        ),
        region_type=str(raw.get("region_type") or "身片"),
        color=normalize_color(raw.get("color")),
        pattern=normalize_pattern(raw.get("pattern")),
        optical=normalize_optical(raw.get("optical")),
        fabric=normalize_fabric(fabric_raw),
        behavior=normalize_behavior(raw.get("behavior")),
        confidence=normalize_region_confidence(raw.get("confidence")),
        # 框非法（越界 / 太小 / 没给）→ 置空，由裁剪侧退化为中心区域
        swatch_crop_box=normalize_box(raw.get("swatch_box")),
        swatch_content_type="image/jpeg",
    )


def normalize_card(raw: Any) -> MaterialCardResult:
    """把模型输出归一化成 `MaterialCardResult`。

    容错：
    - 顶层是数组、或 `{"card": {...}}` 包装 → 取内层对象；
    - 没有 `regions` → 用顶层字段拼一个 `body` / 身片 区域；
    - 给了旧的 `{"tags": [...]}` 形状 → 用第一个 tag 当 `fabric.material` 兜底。
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if isinstance(raw, dict) and isinstance(raw.get("card"), dict):
        raw = raw["card"]
    if not isinstance(raw, dict):
        raw = {}

    raw_regions = raw.get("regions")
    if isinstance(raw_regions, list) and raw_regions:
        regions = [
            normalize_region(item, index=index)
            for index, item in enumerate(raw_regions)
            if isinstance(item, dict)
        ]
    else:
        regions = [normalize_region(raw)]

    # 旧格式兜底：`tags[0].material`
    tags = raw.get("tags")
    if isinstance(tags, list) and tags and not regions[0].fabric.material:
        first = tags[0] if isinstance(tags[0], dict) else {}
        regions[0].fabric = normalize_fabric({"material": first.get("material")})

    confidences = [
        value
        for region in regions
        for value in (
            region.confidence.color,
            region.confidence.pattern,
            region.confidence.gloss,
        )
        if value > 0
    ]
    overall = clamp_confidence(raw.get("overall_confidence"))
    if not overall and confidences:
        overall = round(sum(confidences) / len(confidences), 4)

    return MaterialCardResult(
        category=pick_option(raw.get("category"), CATEGORY_OPTIONS, DEFAULT_CATEGORY),
        regions=regions,
        evidence=str(raw.get("evidence") or "").strip(),
        note=str(raw.get("note") or "").strip(),
        schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
        texture_embedding_ref="",
        overall_confidence=overall,
    )


# --------------------------------------------------------------------------- #
# 序列化（DB payload 列 / 识别缓存共用）
# --------------------------------------------------------------------------- #
def attach_swatch(
    card: MaterialCardResult,
    image_bytes: bytes | None,
    *,
    max_side: int = DEFAULT_SWATCH_MAX_SIDE,
) -> None:
    """按各区域的裁剪框从原图裁出「材质小样」并挂到区域上（就地修改）。

    只有拿到**本地字节**才能裁（外链图在本进程里没有像素）。裁剪失败不影响识别结果 ——
    小样是保真增强项，不该让整个识别失败。

    缓存命中时卡片来自 JSON（没有字节），编排器用同一函数拿原图重裁即可。
    """
    if not image_bytes or not card.regions:
        return

    for region in card.regions:
        cropped = crop_normalized(
            image_bytes, region.swatch_crop_box, max_side=max_side
        )
        if cropped is None:
            continue
        region.swatch_bytes, used_box = cropped
        region.swatch_crop_box = used_box
        region.swatch_content_type = "image/jpeg"


def _region_payload(region: MaterialRegionResult) -> dict[str, Any]:
    return {
        "region_id": region.region_id,
        "region_type": region.region_type,
        "color": {
            "dominant_hex": region.color.dominant_hex,
            "dominant_name": region.color.dominant_name,
            "lab": list(region.color.lab) if region.color.lab else None,
            "palette": region.color.palette,
            "distribution": region.color.distribution,
        },
        "pattern": {
            "type": region.pattern.type,
            "scale": region.pattern.scale,
            "direction": region.pattern.direction,
            "layout": region.pattern.layout,
        },
        "optical": {
            "gloss": region.optical.gloss,
            "transparency": region.optical.transparency,
        },
        "fabric": {
            "material": region.fabric.material,
            "material_en": region.fabric.material_en,
            "category": region.fabric.category,
            "finish": region.fabric.finish,
            "confidence": region.fabric.confidence,
        },
        "behavior": {
            "weight": region.behavior.weight,
            "drape": region.behavior.drape,
            "confidence": region.behavior.confidence,
            "is_default": region.behavior.is_default,
        },
        "confidence": {
            "color": region.confidence.color,
            "pattern": region.confidence.pattern,
            "gloss": region.confidence.gloss,
        },
        "swatch_crop_box": list(region.swatch_crop_box)
        if region.swatch_crop_box
        else None,
    }


def to_payload(card: MaterialCardResult) -> dict[str, Any]:
    """卡片 → 可 JSON 化的字典（不含 swatch 字节：那部分单独落盘）。"""
    return {
        "category": card.category,
        "regions": [_region_payload(region) for region in card.regions],
        "evidence": card.evidence,
        "note": card.note,
        "schema_version": card.schema_version,
        "texture_embedding_ref": card.texture_embedding_ref,
        "overall_confidence": card.overall_confidence,
    }


def from_payload(payload: Any) -> MaterialCardResult:
    """可 JSON 化字典 → 卡片（结构与 `to_payload` 对称）。

    结构与预期不符时返回**空卡片**（无区域）—— 调用方（识别缓存）据此判定缓存已损坏，
    而不是拿一张看似正常的默认卡片冒充识别结果。
    """
    if not isinstance(payload, dict):
        return MaterialCardResult()

    raw_regions = payload.get("regions")
    regions: list[MaterialRegionResult] = []
    if isinstance(raw_regions, list):
        for index, item in enumerate(raw_regions):
            if not isinstance(item, dict):
                continue
            region = normalize_region(item, index=index)
            box = item.get("swatch_crop_box")
            region.swatch_crop_box = (
                tuple(float(value) for value in box)
                if isinstance(box, (list, tuple)) and len(box) == 4
                else None
            )
            regions.append(region)
    if not regions:
        return MaterialCardResult()

    return MaterialCardResult(
        category=str(payload.get("category") or DEFAULT_CATEGORY),
        regions=regions,
        evidence=str(payload.get("evidence") or ""),
        note=str(payload.get("note") or ""),
        schema_version=str(payload.get("schema_version") or SCHEMA_VERSION),
        texture_embedding_ref=str(payload.get("texture_embedding_ref") or ""),
        overall_confidence=clamp_confidence(payload.get("overall_confidence")),
    )


__all__ = [
    "SCHEMA_VERSION",
    "clamp_confidence",
    "normalize_hex",
    "normalize_lab",
    "normalize_palette",
    "pick_option",
    "normalize_color",
    "normalize_pattern",
    "normalize_optical",
    "normalize_fabric",
    "normalize_behavior",
    "normalize_region_confidence",
    "normalize_region",
    "normalize_card",
    "attach_swatch",
    "to_payload",
    "from_payload",
]

"""颜色工具：sRGB ↔ LAB、感知色差（ΔE）与主色提取。

为什么单独一个模块：材质图检索需要两件与「颜色」相关的事 ——

1. 把识别出的**主导色 hex** 变成可检索的英文色词（`nearest_color_name`），
   让颜色信息真正进入检索词（此前中文色名被 `isascii()` 过滤掉）；
2. 给候选面料图算主色，与卡片色板做**感知色差**比较（`dominant_lab_colors` + `delta_e`），
   用于重排 —— Unsplash 不返回相关性分数，颜色是最可靠的可计算信号。

全部为纯函数，方便脱离网络直接单测。
"""

from __future__ import annotations

import io
import re
from PIL import Image, UnidentifiedImageError

from app.abilities.image_ops import to_rgb

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

#: ΔE 达到该值即视为「完全不同的颜色」（归一化用）
DELTA_E_FULL_DISTANCE = 100.0

#: D65 白点（CIE 标准观察者 2°）
_WHITE_POINT = (0.95047, 1.0, 1.08883)

#: 基础英文色参考表 —— 用于把任意 hex 归到可检索的色词
_BASIC_COLORS: tuple[tuple[str, str], ...] = (
    ("black", "#000000"),
    ("dark gray", "#3F3F3F"),
    ("gray", "#808080"),
    ("light gray", "#C0C0C0"),
    ("white", "#FFFFFF"),
    ("cream", "#F5F0DC"),
    ("beige", "#D8C9A8"),
    ("dark brown", "#4A2C17"),
    ("brown", "#8B5A2B"),
    ("red", "#C81E1E"),
    ("pink", "#E8A0B4"),
    ("orange", "#E07B27"),
    ("yellow", "#E8C42B"),
    ("olive", "#7A7A2E"),
    ("green", "#2E7D32"),
    ("teal", "#2E8B8B"),
    ("blue", "#2F5FBF"),
    ("navy blue", "#1B2A4A"),
    ("purple", "#6A3D9A"),
    ("lavender", "#B9A7D6"),
)


def hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    """`#RRGGBB` / `RRGGBB` → (r, g, b)；无法识别返回 None。"""
    if not isinstance(value, str):
        return None
    match = _HEX_RE.match(value.strip())
    if not match:
        return None
    digits = match.group(1)
    return (
        int(digits[0:2], 16),
        int(digits[2:4], 16),
        int(digits[4:6], 16),
    )


def _linearize(channel: int) -> float:
    value = channel / 255.0
    if value <= 0.04045:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def srgb_to_xyz(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = (_linearize(channel) for channel in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    return x, y, z


def _lab_f(value: float) -> float:
    if value > 0.008856:
        return value ** (1.0 / 3.0)
    return 7.787 * value + 16.0 / 116.0


def srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB → CIELAB（D65）。白 → (100, ~0, ~0)，黑 → (0, 0, 0)。"""
    x, y, z = srgb_to_xyz(rgb)
    fx = _lab_f(x / _WHITE_POINT[0])
    fy = _lab_f(y / _WHITE_POINT[1])
    fz = _lab_f(z / _WHITE_POINT[2])
    return (116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz))


def hex_to_lab(value: str) -> tuple[float, float, float] | None:
    rgb = hex_to_rgb(value)
    return srgb_to_lab(rgb) if rgb else None


def delta_e(
    lab_a: tuple[float, float, float], lab_b: tuple[float, float, float]
) -> float:
    """CIE76 色差：LAB 空间欧氏距离（足够区分面料颜色，且零依赖可测）。"""
    return (
        (lab_a[0] - lab_b[0]) ** 2
        + (lab_a[1] - lab_b[1]) ** 2
        + (lab_a[2] - lab_b[2]) ** 2
    ) ** 0.5


def color_similarity(distance: float) -> float:
    """把 ΔE 归一化成 0~1 的相似度（ΔE ≥ 100 视为完全不同）。"""
    clamped = min(max(distance, 0.0), DELTA_E_FULL_DISTANCE)
    return round(1.0 - clamped / DELTA_E_FULL_DISTANCE, 4)


def nearest_color_name(value: str) -> str:
    """把 hex 归到最近的**基础英文色词**（可直接拼进英文检索词）。

    用 LAB 距离而非字面比对 —— 识别模型给的 `dominant_name` 是自由中文文本
    （「深灰蓝」「雾霾蓝」…），无法直接检索；hex 才是可靠的视觉事实。
    """
    lab = hex_to_lab(value)
    if lab is None:
        return ""

    best_name = ""
    best_distance = float("inf")
    for name, reference_hex in _BASIC_COLORS:
        reference_lab = hex_to_lab(reference_hex)
        if reference_lab is None:  # pragma: no cover - 参考表是常量，必然可解析
            continue
        distance = delta_e(lab, reference_lab)
        if distance < best_distance:
            best_distance = distance
            best_name = name
    return best_name


def dominant_lab_colors(
    image_bytes: bytes, *, k: int = 4, sample_side: int = 64
) -> list[tuple[tuple[float, float, float], float]]:
    """提取图片主色（LAB + 占比），按占比降序、最多 `k` 项。

    先缩到 `sample_side` 再量化，对「面料特写」这类近乎均匀的图很稳，也足够快。
    无法解码时返回空列表（调用方应视为「没有颜色信息」，而不是失败）。
    """
    if not image_bytes or k <= 0:
        return []

    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            img = to_rgb(raw)
            img.thumbnail((sample_side, sample_side))
            quantized = img.quantize(colors=max(1, k))
            palette = quantized.getpalette() or []
            counts = quantized.getcolors() or []
    except (OSError, ValueError, UnidentifiedImageError):
        return []

    total = sum(count for count, _ in counts)
    if not total:
        return []

    entries: list[tuple[tuple[float, float, float], float]] = []
    for count, index in sorted(counts, key=lambda item: item[0], reverse=True)[:k]:
        offset = index * 3
        rgb = tuple(palette[offset : offset + 3])
        if len(rgb) != 3:  # pragma: no cover - Pillow 调色板长度固定
            continue
        entries.append((srgb_to_lab(rgb), round(count / total, 4)))
    return entries


def average_lab(image_bytes: bytes) -> tuple[float, float, float] | None:
    """整图平均色（LAB）。用于「几乎单色」的图做快速比对。"""
    colors = dominant_lab_colors(image_bytes, k=1)
    if not colors:
        return None
    return colors[0][0]


__all__ = [
    "DELTA_E_FULL_DISTANCE",
    "hex_to_rgb",
    "hex_to_lab",
    "srgb_to_lab",
    "srgb_to_xyz",
    "delta_e",
    "color_similarity",
    "nearest_color_name",
    "dominant_lab_colors",
    "average_lab",
]

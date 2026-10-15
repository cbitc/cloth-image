"""图片处理工具：缩略图、视觉输入预处理、data URL 编码。

集中在这里，避免这份通用能力散落在各个 provider 里。
"""

from __future__ import annotations

import base64
import io

from PIL import Image, UnidentifiedImageError

# 视觉模型的最佳输入边长（超过后收益递减、token 成本上升）
DEFAULT_VISION_MAX_SIDE = 1568

# 缩略图默认最长边
DEFAULT_THUMBNAIL_SIDE = 384

# 材质小样（swatch）尺寸约束
DEFAULT_SWATCH_MIN_SIDE = 256
DEFAULT_SWATCH_MAX_SIDE = 768
#: 模型没给（或给了非法）裁剪框时，退化为原图中心这一比例的区域
DEFAULT_SWATCH_FALLBACK_FRACTION = 0.6


def to_rgb(img: Image.Image) -> Image.Image:
    """统一转成 RGB（RGBA / 调色板图贴白底，避免透明变黑）。"""
    if img.mode in ("RGB", "L"):
        return img.convert("RGB")
    # PNG 的 RGBA / P 调色板：贴到白底上，避免透明变黑
    background = Image.new("RGB", img.size, (255, 255, 255))
    rgba = img.convert("RGBA")
    background.paste(rgba, mask=rgba.split()[-1])
    return background


#: 兼容模块内既有调用（历史名称）
_to_rgb = to_rgb


def make_thumbnail(image_bytes: bytes, max_size: int = DEFAULT_THUMBNAIL_SIDE) -> bytes:
    """从原图生成 JPEG 缩略图。"""
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = _to_rgb(img)
        img.thumbnail((max_size, max_size))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=82, optimize=True)
        return buffer.getvalue()


def encode_image(
    image_bytes: bytes,
    *,
    max_side: int | None = None,
    max_bytes: int | None = None,
    start_quality: int = 88,
    min_quality: int = 45,
) -> tuple[bytes, str]:
    """等比缩放并编码为 JPEG。返回 (内容, mime)。

    超过 max_side 会等比缩小；超过 max_bytes 会逐步降低 JPEG 质量。
    小图不会被放大。
    """
    with Image.open(io.BytesIO(image_bytes)) as img:
        img = _to_rgb(img)
        if max_side and max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)

        quality = start_quality
        while True:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if not max_bytes or len(data) <= max_bytes or quality <= min_quality:
                break
            quality -= 15

    return data, "image/jpeg"


def to_data_url(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def prepare_vision_image(
    image_bytes: bytes,
    *,
    max_side: int = DEFAULT_VISION_MAX_SIDE,
    max_bytes: int = 4_000_000,
) -> tuple[bytes, str, str]:
    """视觉模型输入预处理。

    返回 (内容, mime, data_url)。使用 data URL 而非自家 URL，
    因为外部服务无法访问本机的 /media 地址。
    """
    data, mime = encode_image(image_bytes, max_side=max_side, max_bytes=max_bytes)
    return data, mime, to_data_url(data, mime)


def reference_data_url(
    image_bytes: bytes,
    *,
    max_side: int = 1024,
    max_bytes: int = 2_000_000,
) -> str:
    """生图参考图的 data URL（比视觉输入更严格地限制体积）。"""
    data, mime = encode_image(image_bytes, max_side=max_side, max_bytes=max_bytes)
    return to_data_url(data, mime)


def normalize_box(
    box: object,
) -> tuple[float, float, float, float] | None:
    """校验归一化裁剪框 (left, top, right, bottom)。

    要求四个分量都在 0~1、且宽高不小于 5%；否则返回 None（调用方退化为中心裁剪）。
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        left, top, right, bottom = (float(value) for value in box)
    except (TypeError, ValueError):
        return None

    if not all(0.0 <= value <= 1.0 for value in (left, top, right, bottom)):
        return None
    if right - left < 0.05 or bottom - top < 0.05:
        return None
    return left, top, right, bottom


def crop_normalized(
    image_bytes: bytes,
    box: object,
    *,
    min_side: int = DEFAULT_SWATCH_MIN_SIDE,
    max_side: int = DEFAULT_SWATCH_MAX_SIDE,
    fallback_fraction: float = DEFAULT_SWATCH_FALLBACK_FRACTION,
) -> tuple[bytes, tuple[float, float, float, float]] | None:
    """按归一化框裁剪「材质小样」（干净面料 patch）。

    返回 (JPEG 字节, 实际使用的归一化框)；图片无法解码或尺寸过小时返回 None。
    传入的框非法（模型没给 / 越界 / 太小）时退化为原图中心 `fallback_fraction` 区域 ——
    小样是生成阶段的保真锚点，宁可区域不完美也不要缺这个字段。
    """
    if not image_bytes:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            img = _to_rgb(raw)
            width, height = img.size
            if width < 8 or height < 8:
                return None

            norm = normalize_box(box)
            if norm is None:
                half = fallback_fraction / 2
                norm = (0.5 - half, 0.5 - half, 0.5 + half, 0.5 + half)

            left = min(max(int(norm[0] * width), 0), width - 8)
            top = min(max(int(norm[1] * height), 0), height - 8)
            right = min(max(int(norm[2] * width), left + 8), width)
            bottom = min(max(int(norm[3] * height), top + 8), height)

            patch = img.crop((left, top, right, bottom))
            if min(patch.size) < min_side:
                scale = min_side / min(patch.size)
                patch = patch.resize(
                    (
                        max(1, round(patch.size[0] * scale)),
                        max(1, round(patch.size[1] * scale)),
                    ),
                    Image.LANCZOS,
                )
            if max(patch.size) > max_side:
                patch.thumbnail((max_side, max_side), Image.LANCZOS)

            buffer = io.BytesIO()
            patch.save(buffer, format="JPEG", quality=88, optimize=True)
    except (OSError, ValueError, UnidentifiedImageError):
        return None

    used = (
        round(left / width, 4),
        round(top / height, 4),
        round(right / width, 4),
        round(bottom / height, 4),
    )
    return buffer.getvalue(), used

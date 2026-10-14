"""图片处理工具：缩略图、视觉输入预处理、data URL 编码。

集中在这里，避免这份通用能力散落在各个 provider 里。
"""

from __future__ import annotations

import base64
import io

from PIL import Image

# 视觉模型的最佳输入边长（超过后收益递减、token 成本上升）
DEFAULT_VISION_MAX_SIDE = 1568

# 缩略图默认最长边
DEFAULT_THUMBNAIL_SIDE = 384


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "L"):
        return img.convert("RGB")
    # PNG 的 RGBA / P 调色板：贴到白底上，避免透明变黑
    background = Image.new("RGB", img.size, (255, 255, 255))
    rgba = img.convert("RGBA")
    background.paste(rgba, mask=rgba.split()[-1])
    return background


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

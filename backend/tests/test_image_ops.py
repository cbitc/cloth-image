"""图片处理工具测试（离线，不依赖网络）。"""

from __future__ import annotations

import io
import random

from PIL import Image

from app.abilities.image_ops import (
    encode_image,
    make_thumbnail,
    prepare_vision_image,
    reference_data_url,
    to_data_url,
)


def _png(width: int, height: int, color: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _noise_png(size: int) -> bytes:
    random.seed(0)
    image = Image.new("RGB", (size, size))
    image.putdata([(random.randint(0, 255),) * 3 for _ in range(size * size)])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_vision_image_downscales_and_keeps_aspect() -> None:
    data, mime, data_url = prepare_vision_image(_png(3000, 1500), max_side=1568)

    assert mime == "image/jpeg"
    assert data_url.startswith("data:image/jpeg;base64,")

    with Image.open(io.BytesIO(data)) as image:
        assert max(image.size) <= 1568
        assert image.size[0] == 1568
        assert abs(image.size[0] / image.size[1] - 2.0) < 0.02


def test_prepare_vision_image_does_not_upscale_small_images() -> None:
    data, _, _ = prepare_vision_image(_png(200, 100), max_side=1568)
    with Image.open(io.BytesIO(data)) as image:
        assert image.size == (200, 100)


def test_transparent_png_gets_white_background_not_black() -> None:
    image = Image.new("RGBA", (40, 40), (255, 0, 0, 0))  # 全透明
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    data, _, _ = prepare_vision_image(buffer.getvalue(), max_side=64)
    with Image.open(io.BytesIO(data)) as out:
        pixel = out.convert("RGB").getpixel((20, 20))

    assert all(channel > 240 for channel in pixel)


def test_encode_image_lowers_quality_to_meet_max_bytes() -> None:
    source = _noise_png(900)

    unrestricted, _ = encode_image(source, max_side=900, max_bytes=None)
    limited, _ = encode_image(source, max_side=900, max_bytes=50_000)

    assert len(limited) < len(unrestricted)
    with Image.open(io.BytesIO(limited)) as image:
        assert image.size == (900, 900)  # 尺寸不变，只降质量


def test_make_thumbnail_preserves_aspect_ratio() -> None:
    thumb = make_thumbnail(_png(1200, 600), max_size=384)
    with Image.open(io.BytesIO(thumb)) as image:
        assert image.size == (384, 192)
        assert image.format == "JPEG"


def test_data_url_helpers_prefix() -> None:
    raw = _png(32, 32)
    assert to_data_url(raw, "image/png").startswith("data:image/png;base64,")
    assert reference_data_url(raw, max_side=64).startswith("data:image/jpeg;base64,")

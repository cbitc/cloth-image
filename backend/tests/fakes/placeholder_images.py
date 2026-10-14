"""确定性占位图生成（Pillow）。

测试用 fake provider 用它生成「看起来像那么回事」的服装图 / 面料图 / 设计图，
使得整条流水线无需任何外部素材或网络即可跑通。

注意：绘制文字只用 ASCII，避免默认字体无法渲染中文。
"""

from __future__ import annotations

import colorsys
import hashlib
import io
import random
import textwrap

from PIL import Image, ImageDraw, ImageFont

KIND_CLOTHING = "clothing"
KIND_MATERIAL = "material"
KIND_DESIGN = "design"


def _seed_int(seed: str) -> int:
    return int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:8], "big")


def _hsl(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _font(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _gradient(
    size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    img = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(size - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def _draw_clothing(
    img: Image.Image, rng: random.Random, label: str, footer: str
) -> None:
    size = img.size[0]
    draw = ImageDraw.Draw(img, "RGBA")

    # 身体轮廓（简单梯形 + 肩线）
    cx = size / 2
    top_w, bottom_w = size * 0.28, size * 0.44
    top_y, bottom_y = size * 0.26, size * 0.82
    dark = (0, 0, 0, 40)
    draw.polygon(
        [
            (cx - top_w / 2, top_y),
            (cx + top_w / 2, top_y),
            (cx + bottom_w / 2, bottom_y),
            (cx - bottom_w / 2, bottom_y),
        ],
        fill=dark,
        outline=(255, 255, 255, 120),
        width=3,
    )
    # 领口
    draw.ellipse(
        [cx - size * 0.07, top_y - size * 0.03, cx + size * 0.07, top_y + size * 0.07],
        outline=(255, 255, 255, 140),
        width=3,
    )
    # 随机装饰线
    for _ in range(3):
        y = rng.uniform(top_y + 40, bottom_y - 40)
        draw.line(
            [(cx - size * 0.14, y), (cx + size * 0.14, y)],
            fill=(255, 255, 255, 45),
            width=2,
        )

    draw.text(
        (size * 0.04, size * 0.06),
        label,
        font=_font(int(size * 0.055)),
        fill=(255, 255, 255),
    )
    if footer:
        draw.text(
            (size * 0.04, size * 0.90),
            footer,
            font=_font(int(size * 0.032)),
            fill=(255, 255, 255, 200),
        )


def _draw_material(img: Image.Image, rng: random.Random, label: str) -> None:
    size = img.size[0]
    draw = ImageDraw.Draw(img, "RGBA")
    pattern = rng.randrange(3)

    if pattern == 0:  # 条纹
        step = rng.choice([8, 12, 16])
        for x in range(0, size, step):
            alpha = rng.randint(20, 60)
            draw.line([(x, 0), (x, size)], fill=(255, 255, 255, alpha), width=2)
        for y in range(0, size, step * 3):
            draw.line([(0, y), (size, y)], fill=(0, 0, 0, 25), width=1)
    elif pattern == 1:  # 编织网格
        step = rng.choice([14, 20, 26])
        for x in range(0, size, step):
            draw.line([(x, 0), (x, size)], fill=(255, 255, 255, 35), width=1)
        for y in range(0, size, step):
            draw.line([(0, y), (size, y)], fill=(0, 0, 0, 35), width=1)
    else:  # 颗粒
        for _ in range(int(size * size / 90)):
            x, y = rng.randrange(size), rng.randrange(size)
            v = rng.randint(0, 60)
            draw.point((x, y), fill=(v, v, v, 90))

    # 柔和高光，模拟光泽
    for _ in range(2):
        r = rng.randint(int(size * 0.2), int(size * 0.45))
        cx, cy = rng.randint(0, size), rng.randint(0, size)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(255, 255, 255, rng.randint(8, 20)),
        )

    # 底部标签条
    bar_h = int(size * 0.12)
    draw.rectangle([0, size - bar_h, size, size], fill=(0, 0, 0, 130))
    draw.text(
        (size * 0.05, size - bar_h * 0.78),
        label,
        font=_font(int(size * 0.042)),
        fill=(255, 255, 255),
    )


def _draw_design(img: Image.Image, rng: random.Random, label: str) -> None:
    size = img.size[0]
    draw = ImageDraw.Draw(img, "RGBA")
    cx = size / 2

    # 简化连衣裙剪影
    draw.polygon(
        [
            (cx - size * 0.13, size * 0.22),
            (cx + size * 0.13, size * 0.22),
            (cx + size * 0.09, size * 0.45),
            (cx + size * 0.24, size * 0.84),
            (cx - size * 0.24, size * 0.84),
            (cx - size * 0.09, size * 0.45),
        ],
        fill=(255, 255, 255, 55),
        outline=(255, 255, 255, 170),
    )
    # 袖
    draw.polygon(
        [
            (cx - size * 0.13, size * 0.23),
            (cx - size * 0.30, size * 0.34),
            (cx - size * 0.26, size * 0.48),
            (cx - size * 0.11, size * 0.40),
        ],
        fill=(255, 255, 255, 45),
        outline=(255, 255, 255, 150),
    )
    draw.polygon(
        [
            (cx + size * 0.13, size * 0.23),
            (cx + size * 0.30, size * 0.34),
            (cx + size * 0.26, size * 0.48),
            (cx + size * 0.11, size * 0.40),
        ],
        fill=(255, 255, 255, 45),
        outline=(255, 255, 255, 150),
    )
    for _ in range(4):
        y = rng.uniform(size * 0.5, size * 0.8)
        draw.line(
            [(cx - size * 0.20, y), (cx + size * 0.20, y)],
            fill=(255, 255, 255, 40),
            width=2,
        )
    draw.text(
        (size * 0.04, size * 0.06),
        label,
        font=_font(int(size * 0.05)),
        fill=(255, 255, 255),
    )
    draw.text(
        (size * 0.04, size * 0.90),
        "PLACEHOLDER",
        font=_font(int(size * 0.03)),
        fill=(255, 255, 255, 190),
    )


def make_image(
    *,
    seed: str,
    label: str,
    kind: str = KIND_CLOTHING,
    size: int = 768,
    footer: str = "",
) -> bytes:
    """生成确定性的 PNG 图片字节。相同 seed 必得相同图片。"""
    rng = random.Random(_seed_int(seed))
    hue = rng.random()
    if kind == KIND_MATERIAL:
        top = _hsl(hue, 0.22, rng.uniform(0.32, 0.5))
        bottom = _hsl(hue + 0.02, 0.25, rng.uniform(0.18, 0.3))
    elif kind == KIND_DESIGN:
        top = _hsl(hue, 0.42, rng.uniform(0.48, 0.62))
        bottom = _hsl(hue + 0.12, 0.5, rng.uniform(0.22, 0.34))
    else:
        top = _hsl(hue, 0.35, rng.uniform(0.55, 0.68))
        bottom = _hsl(hue + 0.08, 0.4, rng.uniform(0.28, 0.4))

    img = _gradient(size, top, bottom)
    if kind == KIND_MATERIAL:
        _draw_material(img, rng, label)
    elif kind == KIND_DESIGN:
        _draw_design(img, rng, label)
    else:
        _draw_clothing(img, rng, label, footer)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def wrap_text(text: str, width: int = 40) -> str:
    return "\n".join(textwrap.wrap(text, width))

"""颜色工具单测：sRGB→LAB、色差、色名映射、主色提取。"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.abilities.color_ops import (
    DELTA_E_FULL_DISTANCE,
    color_similarity,
    delta_e,
    dominant_lab_colors,
    hex_to_lab,
    hex_to_rgb,
    nearest_color_name,
    srgb_to_lab,
)


def _solid_png(rgb: tuple[int, int, int], size: int = 16) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), rgb).save(buffer, format="PNG")
    return buffer.getvalue()


def test_hex_to_rgb_accepts_with_and_without_hash() -> None:
    assert hex_to_rgb("#2B3A4A") == (0x2B, 0x3A, 0x4A)
    assert hex_to_rgb("2b3a4a") == (0x2B, 0x3A, 0x4A)
    assert hex_to_rgb("#XYZ") is None
    assert hex_to_rgb("") is None


def test_srgb_to_lab_matches_reference_points() -> None:
    assert srgb_to_lab((255, 255, 255)) == pytest.approx((100.0, 0.0, 0.0), abs=0.05)
    assert srgb_to_lab((0, 0, 0)) == pytest.approx((0.0, 0.0, 0.0), abs=0.01)


def test_delta_e_is_zero_for_identical_colour_and_grows_with_distance() -> None:
    base = hex_to_lab("#808080")
    near = hex_to_lab("#909090")
    far = hex_to_lab("#FFFFFF")
    assert base is not None and near is not None and far is not None

    assert delta_e(base, base) == pytest.approx(0.0)
    assert delta_e(base, far) > delta_e(base, near)
    assert delta_e(base, near) == pytest.approx(delta_e(near, base))  # 对称


def test_color_similarity_bounds() -> None:
    assert color_similarity(0.0) == pytest.approx(1.0)
    assert color_similarity(DELTA_E_FULL_DISTANCE) == pytest.approx(0.0)
    assert color_similarity(DELTA_E_FULL_DISTANCE * 3) == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("hex_value", "expected"),
    [
        ("#000000", "black"),
        ("#FFFFFF", "white"),
        ("#1B2A4A", "navy blue"),
        ("#C81E1E", "red"),
        ("#2E7D32", "green"),
        ("#C02020", "red"),  # 非参考表原值：应归到最近的色词
    ],
)
def test_nearest_color_name(hex_value: str, expected: str) -> None:
    assert nearest_color_name(hex_value) == expected


def test_nearest_color_name_returns_empty_for_unparseable_values() -> None:
    # 中文自由文本色名正是要解决的对象：不能解析就不要猜
    assert nearest_color_name("深灰蓝") == ""
    assert nearest_color_name("") == ""


def test_dominant_lab_colors_finds_the_only_colour() -> None:
    colors = dominant_lab_colors(_solid_png((200, 30, 30)))
    assert colors

    lab, weight = colors[0]
    assert weight == pytest.approx(1.0)
    assert delta_e(lab, srgb_to_lab((200, 30, 30))) < 2.0


def test_dominant_lab_colors_degrades_to_empty_on_garbage() -> None:
    assert dominant_lab_colors(b"not an image") == []
    assert dominant_lab_colors(b"") == []
    assert dominant_lab_colors(_solid_png((1, 2, 3)), k=0) == []

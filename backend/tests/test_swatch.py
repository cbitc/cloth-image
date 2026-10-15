"""材质小样（swatch）裁取与落盘。

小样是「生成阶段」的保真锚点（MVP 计划 §3.2 的参考轨），所以它必须：
- 按模型给的干净面料框裁出来（而非整图缩放）
- 模型给的框非法时退化为中心区域，而不是让小样为空
- 真实落盘并通过 /media 提供（前端要能预览）
"""

from __future__ import annotations

import io

from PIL import Image

from app.abilities.image_ops import crop_normalized, normalize_box
from app.enums import TaskStatus


def _png(width: int = 800, height: int = 600, color=(30, 60, 90)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
def test_normalize_box_rejects_bad_shapes_and_tiny_boxes() -> None:
    assert normalize_box([0.1, 0.1, 0.6, 0.6]) == (0.1, 0.1, 0.6, 0.6)
    assert normalize_box(None) is None
    assert normalize_box([0.1, 0.1, 0.6]) is None
    assert normalize_box([0.1, 0.1, 0.6, 1.4]) is None  # 越界
    assert normalize_box([0.1, 0.1, 0.12, 0.6]) is None  # 太窄
    assert normalize_box(["a", 0.1, 0.6, 0.6]) is None


def test_crop_uses_the_requested_box() -> None:
    data, box = crop_normalized(_png(800, 600), [0.25, 0.25, 0.75, 0.75])
    assert box == (0.25, 0.25, 0.75, 0.75)
    # 0.5 × 800 = 400，0.5 × 600 = 300 → 按框裁，不整图缩放
    assert _size(data) == (400, 300)


def test_crop_upscales_small_patches_to_min_side() -> None:
    # 100×100 的图上取 20% → 20×20，应被放大到最小边
    data, _ = crop_normalized(_png(100, 100), [0.1, 0.1, 0.3, 0.3], min_side=256)
    assert min(_size(data)) == 256


def test_crop_falls_back_to_center_for_invalid_box() -> None:
    data, box = crop_normalized(_png(), [0.99, 0.99, 1.5, 1.5])
    assert box == (0.2, 0.2, 0.8, 0.8)
    assert data


def test_crop_returns_none_for_undecodable_bytes() -> None:
    assert crop_normalized(b"not-an-image", [0.1, 0.1, 0.6, 0.6]) is None
    assert crop_normalized(b"", None) is None


def test_crop_is_deterministic() -> None:
    first = crop_normalized(_png(), [0.2, 0.3, 0.7, 0.8])
    second = crop_normalized(_png(), [0.2, 0.3, 0.7, 0.8])
    assert first == second


# --------------------------------------------------------------------------- #
# 与流水线打通
# --------------------------------------------------------------------------- #
def test_swatch_is_persisted_and_served(client, sample_clothing_image_id) -> None:
    resp = client.post(
        "/api/tasks", json={"clothing_image_ids": [sample_clothing_image_id]}
    )
    task_id = resp.json()["tasks"][0]["id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_MATERIAL_CONFIRM
    swatch = detail["material_card"]["swatch"]

    assert swatch["url"], "识别后小样必须落盘"
    assert swatch["crop_box"] and len(swatch["crop_box"]) == 4
    assert all(0.0 <= value <= 1.0 for value in swatch["crop_box"])

    media = client.get(swatch["url"].replace("http://testserver", ""))
    assert media.status_code == 200, media.text
    assert media.headers["content-type"].startswith("image/")

    thumb = client.get(swatch["thumbnail_url"].replace("http://testserver", ""))
    assert thumb.status_code == 200, thumb.text


def test_editing_attributes_keeps_the_swatch(client, sample_clothing_image_id) -> None:
    """小样是参考轨、属性是语义轨：改属性不该把参考轨清掉。"""
    resp = client.post(
        "/api/tasks", json={"clothing_image_ids": [sample_clothing_image_id]}
    )
    task_id = resp.json()["tasks"][0]["id"]
    before = client.get(f"/api/tasks/{task_id}").json()["material_card"]["swatch"]

    after = client.put(
        f"/api/tasks/{task_id}/material-card",
        json={"region": {"optical": {"gloss": "微光"}}},
    ).json()["material_card"]["swatch"]

    assert after == before

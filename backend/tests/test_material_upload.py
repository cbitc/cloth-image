"""用户上传面料图（MVP 计划 §4.3 编辑入口 2「换小样」）。

上传图与检索结果同在 `material_image` 池里参与生图，区别只在 `origin`：
- 重跑材质检索时**只清** `origin=search` 的行 → 用户上传的东西不会被覆盖
- 上传是「强改变」：它直接进参考图池，生图时按参考图注入
"""

from __future__ import annotations

import io

from PIL import Image

from app.enums import TaskStatus


def _png(color: tuple[int, int, int] = (200, 120, 60), size: int = 64) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _task_id(client, sample_clothing_image_id: str) -> str:
    resp = client.post(
        "/api/tasks", json={"clothing_image_ids": [sample_clothing_image_id]}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]["id"]


def _confirm(client, task_id: str) -> dict:
    resp = client.post(f"/api/tasks/{task_id}/confirm-materials")
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/tasks/{task_id}").json()


def test_upload_adds_images_to_the_reference_pool(
    client, sample_clothing_image_id
) -> None:
    task_id = _task_id(client, sample_clothing_image_id)
    detail = _confirm(client, task_id)
    before = len(detail["material_images"])

    resp = client.post(
        f"/api/tasks/{task_id}/material-images",
        files=[
            ("files", ("fabric-a.png", _png((10, 20, 30)), "image/png")),
            ("files", ("fabric-b.png", _png((40, 50, 60)), "image/jpeg")),
        ],
    )
    assert resp.status_code == 200, resp.text
    images = resp.json()["material_images"]

    assert len(images) == before + 2
    uploaded = [image for image in images if image["origin"] == "upload"]
    assert len(uploaded) == 2
    assert {image["label"] for image in uploaded} == {"上传的面料图"}
    assert all(image["image_url"] for image in uploaded)
    assert all(image["selected"] for image in uploaded)

    # 落盘的图能通过 /media 取到
    media = client.get(uploaded[0]["image_url"].replace("http://testserver", ""))
    assert media.status_code == 200, media.text


def test_rerunning_material_search_keeps_uploaded_images(
    client, sample_clothing_image_id
) -> None:
    """改完卡片再确认（重跑检索）时，用户上传的图必须还在。"""
    task_id = _task_id(client, sample_clothing_image_id)
    _confirm(client, task_id)

    client.post(
        f"/api/tasks/{task_id}/material-images",
        files=[("files", ("fabric.png", _png(), "image/png"))],
    )
    uploaded = [
        image
        for image in client.get(f"/api/tasks/{task_id}").json()["material_images"]
        if image["origin"] == "upload"
    ]
    assert len(uploaded) == 1
    uploaded_id = uploaded[0]["id"]

    # 改面料名后再次确认 → 重跑检索
    client.put(
        f"/api/tasks/{task_id}/material-card",
        json={"region": {"fabric": {"material": "棉"}}},
    )
    detail = _confirm(client, task_id)

    ids = {image["id"] for image in detail["material_images"]}
    assert uploaded_id in ids, "重跑检索把用户上传的面料图删掉了"
    assert {image["label"] for image in detail["material_images"]} == {
        "棉",
        "上传的面料图",
    }
    assert all(
        image["origin"] == "search"
        for image in detail["material_images"]
        if image["id"] != uploaded_id
    )


def test_uploaded_image_participates_in_generation(
    client, sample_clothing_image_id
) -> None:
    task_id = _task_id(client, sample_clothing_image_id)
    _confirm(client, task_id)
    client.post(
        f"/api/tasks/{task_id}/material-images",
        files=[("files", ("fabric.png", _png(), "image/png"))],
    )

    resp = client.post(
        f"/api/tasks/{task_id}/generate",
        json={"design_idea": "换成这个面料", "num_candidates": 1},
    )
    assert resp.status_code == 200, resp.text
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.DONE
    # 参考图池非空 → prompt 里应当出现参考图图例（含上传的面料图）
    assert "面料质感参考图" in detail["design_images"][0]["prompt"]


def test_upload_can_be_removed(client, sample_clothing_image_id) -> None:
    task_id = _task_id(client, sample_clothing_image_id)
    _confirm(client, task_id)

    created = client.post(
        f"/api/tasks/{task_id}/material-images",
        files=[("files", ("fabric.png", _png(), "image/png"))],
    ).json()["material_images"]
    uploaded = next(image for image in created if image["origin"] == "upload")

    resp = client.delete(f"/api/tasks/{task_id}/material-images/{uploaded['id']}")
    assert resp.status_code == 200, resp.text
    remaining = resp.json()["material_images"]
    assert all(image["id"] != uploaded["id"] for image in remaining)

    missing = client.delete(f"/api/tasks/{task_id}/material-images/{uploaded['id']}")
    assert missing.status_code == 404


def test_empty_upload_is_rejected(client, sample_clothing_image_id) -> None:
    task_id = _task_id(client, sample_clothing_image_id)
    _confirm(client, task_id)

    resp = client.post(
        f"/api/tasks/{task_id}/material-images",
        files=[("files", ("empty.png", b"", "image/png"))],
    )
    assert resp.status_code == 400, resp.text


def test_upload_on_unknown_task_returns_404(client) -> None:
    resp = client.post(
        "/api/tasks/nope/material-images",
        files=[("files", ("fabric.png", _png(), "image/png"))],
    )
    assert resp.status_code == 404

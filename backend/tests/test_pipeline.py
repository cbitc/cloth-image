"""端到端流水线测试（TASK_EXECUTION=sync，请求内同步执行）。"""

from __future__ import annotations

from app.enums import TaskStatus

DESIGN_IDEA = "改成收腰版型，裙摆加长到脚踝，保留原袖型"


def _create_task(client, clothing_image_id: str, **kwargs) -> dict:
    payload = {"clothing_image_ids": [clothing_image_id]}
    payload.update(kwargs)
    resp = client.post("/api/tasks", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]


def test_health(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["provider_mode"] == "mock"


def test_search_clothing(client) -> None:
    resp = client.post(
        "/api/search/clothing",
        json={"sites": ["mock-shop", "mock-lookbook"], "query": "大衣", "count": 4},
    )
    assert resp.status_code == 200
    images = resp.json()["images"]
    assert len(images) == 4
    assert all(img["image_url"] for img in images)
    assert all(img["page_url"] for img in images)  # 溯源字段

    media = client.get(images[0]["image_url"].replace("http://testserver", ""))
    assert media.status_code == 200
    assert media.headers["content-type"].startswith("image/")


def test_full_pipeline_manual_checkpoints(client, sample_clothing_image_id) -> None:
    task = _create_task(client, sample_clothing_image_id)
    task_id = task["id"]

    # 说明：sync 模式下请求返回时第一阶段已执行完
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_MATERIAL_CONFIRM
    assert 2 <= len(detail["material_tags"]) <= 4

    # 检查点 1：用户确认（改写第一个 tag）
    tags = [
        {
            "material": "桑蚕丝",
            "material_en": "Mulberry Silk",
            "confidence": 0.91,
            "evidence": "用户确认：强光泽、细腻垂坠",
            "category": "天然纤维",
        },
        {
            "material": "醋酸",
            "material_en": "Acetate",
            "confidence": 0.62,
            "evidence": "用户补充候选",
            "category": "再生纤维",
        },
    ]
    resp = client.post(f"/api/tasks/{task_id}/confirm-materials", json={"tags": tags})
    assert resp.status_code == 200, resp.text

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert [t["material"] for t in detail["material_tags"]] == ["桑蚕丝", "醋酸"]
    assert all(t["source"] == "user" for t in detail["material_tags"])
    assert detail["status"] == TaskStatus.AWAIT_DESIGN_IDEA
    assert len(detail["material_images"]) == 2 * 3  # 2 个 tag × 每 tag 3 张
    assert all(m["image_url"] for m in detail["material_images"])

    # 检查点 3：填设计想法 → 生成
    resp = client.post(
        f"/api/tasks/{task_id}/generate",
        json={"design_idea": DESIGN_IDEA, "num_candidates": 2},
    )
    assert resp.status_code == 200, resp.text

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.DONE
    assert detail["design_idea"] == DESIGN_IDEA
    assert len(detail["design_images"]) == 2
    assert all(d["is_mock"] for d in detail["design_images"])
    assert DESIGN_IDEA in detail["design_images"][0]["prompt"]

    # 事件流可用于进度展示
    stages = {e["stage"] for e in detail["events"]}
    assert {"identify", "material_search", "generate"} <= stages


def test_pipeline_with_material_selection_checkpoint(
    client, sample_clothing_image_id
) -> None:
    task = _create_task(
        client, sample_clothing_image_id, require_material_selection=True
    )
    task_id = task["id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    tags = [
        {
            "material": t["material"],
            "confidence": t["confidence"],
            "evidence": t["evidence"],
        }
        for t in detail["material_tags"]
    ]
    client.post(f"/api/tasks/{task_id}/confirm-materials", json={"tags": tags})

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_MATERIAL_SELECT

    keep = [detail["material_images"][0]["id"], detail["material_images"][1]["id"]]
    resp = client.post(
        f"/api/tasks/{task_id}/select-materials", json={"material_image_ids": keep}
    )
    assert resp.status_code == 200, resp.text

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_DESIGN_IDEA
    assert sum(1 for m in detail["material_images"] if m["selected"]) == 2


def test_auto_generate_flow(client, sample_clothing_image_id) -> None:
    task = _create_task(
        client,
        sample_clothing_image_id,
        design_idea=DESIGN_IDEA,
        auto_generate=True,
    )
    task_id = task["id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    tags = [
        {
            "material": t["material"],
            "confidence": t["confidence"],
            "evidence": t["evidence"],
        }
        for t in detail["material_tags"]
    ]
    client.post(f"/api/tasks/{task_id}/confirm-materials", json={"tags": tags})

    # 确认后自动串联：材质检索 → 生成 → DONE
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.DONE
    assert detail["design_images"]


def test_illegal_action_returns_409(client, sample_clothing_image_id) -> None:
    task = _create_task(client, sample_clothing_image_id)
    task_id = task["id"]
    # 还没确认材质就想生成
    resp = client.post(
        f"/api/tasks/{task_id}/generate", json={"design_idea": "x", "num_candidates": 1}
    )
    assert resp.status_code == 409


def test_board_stream_lists_tasks(client, sample_clothing_image_id) -> None:
    resp = client.get("/api/tasks?limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

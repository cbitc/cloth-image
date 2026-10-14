"""批量删除任务接口测试。"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import MaterialTag, Task, TaskEvent
from app.db.session import SessionLocal


def _create_task(client, clothing_image_id: str) -> dict:
    resp = client.post("/api/tasks", json={"clothing_image_ids": [clothing_image_id]})
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]


def _count(db, model, task_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(model.task_id == task_id)
    ).scalar_one()


def test_bulk_delete_removes_tasks_and_cascades(
    client, sample_clothing_image_id
) -> None:
    first = _create_task(client, sample_clothing_image_id)
    second = _create_task(client, sample_clothing_image_id)

    resp = client.post(
        "/api/tasks/bulk-delete", json={"task_ids": [first["id"], second["id"]]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": 2, "not_found": []}

    assert client.get(f"/api/tasks/{first['id']}").status_code == 404
    assert client.get(f"/api/tasks/{second['id']}").status_code == 404

    listed = {task["id"] for task in client.get("/api/tasks").json()}
    assert first["id"] not in listed
    assert second["id"] not in listed

    # 级联：材质 tag 与任务事件也应一并删除（否则会留下孤儿行）
    with SessionLocal() as db:
        for task_id in (first["id"], second["id"]):
            assert db.get(Task, task_id) is None
            assert _count(db, MaterialTag, task_id) == 0
            assert _count(db, TaskEvent, task_id) == 0


def test_bulk_delete_reports_missing_ids(client, sample_clothing_image_id) -> None:
    task = _create_task(client, sample_clothing_image_id)

    body = client.post(
        "/api/tasks/bulk-delete",
        json={"task_ids": [task["id"], "does-not-exist"]},
    ).json()

    assert body == {"deleted": 1, "not_found": ["does-not-exist"]}


def test_bulk_delete_dedupes_ids(client, sample_clothing_image_id) -> None:
    task = _create_task(client, sample_clothing_image_id)

    body = client.post(
        "/api/tasks/bulk-delete", json={"task_ids": [task["id"], task["id"]]}
    ).json()

    assert body == {"deleted": 1, "not_found": []}


def test_bulk_delete_allows_non_terminal_tasks(
    client, sample_clothing_image_id
) -> None:
    """与单删一致：不限制状态（待人工确认也不算终态，同样可删）。"""
    task = _create_task(client, sample_clothing_image_id)
    assert client.get(f"/api/tasks/{task['id']}").json()["status"] == (
        "AWAIT_MATERIAL_CONFIRM"
    )

    body = client.post("/api/tasks/bulk-delete", json={"task_ids": [task["id"]]}).json()

    assert body["deleted"] == 1


def test_bulk_delete_requires_at_least_one_id(client) -> None:
    resp = client.post("/api/tasks/bulk-delete", json={"task_ids": []})
    assert resp.status_code == 422

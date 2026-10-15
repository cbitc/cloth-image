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


def _confirm(client, task_id: str) -> dict:
    """检查点 1：确认材质卡片（不再需要传 tags）。"""
    resp = client.post(f"/api/tasks/{task_id}/confirm-materials")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _patch_card(client, task_id: str, patch: dict) -> dict:
    resp = client.put(f"/api/tasks/{task_id}/material-card", json=patch)
    assert resp.status_code == 200, resp.text
    return resp.json()["material_card"]


def test_health(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert set(resp.json()["abilities"].values()) == {"fake"}


def test_search_clothing(client) -> None:
    resp = client.post(
        "/api/search/clothing",
        json={"sites": ["fake-shop", "fake-lookbook"], "query": "大衣", "count": 4},
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
    assert detail["has_material_card"] is True

    card = detail["material_card"]
    assert card and card["regions"]
    region = card["regions"][0]
    assert region["region_id"] == "body"
    assert region["color"]["dominant_hex"].startswith("#")
    assert region["pattern"]["type"]
    assert region["optical"]["gloss"]
    assert all(
        0.0 <= region["confidence"][key] <= 1.0 for key in ("color", "pattern", "gloss")
    )
    assert card["swatch"]["url"]  # 小样已落盘（生成阶段的保真锚点）
    assert card["swatch"]["crop_box"]
    assert card["source"] == "ai"

    # 检查点 1：用户改属性（图案 / 光泽 / 面料）并写备注
    updated = _patch_card(
        client,
        task_id,
        {
            "category": "连衣裙",
            "note": "面料要更挺括一点",
            "region": {
                "pattern": {"type": "条纹"},
                "optical": {"gloss": "缎面"},
                "fabric": {"material": "醋酸"},
            },
        },
    )
    edited = updated["regions"][0]
    assert updated["source"] == "user"
    assert edited["pattern"]["type"] == "条纹"
    assert edited["optical"]["gloss"] == "缎面"
    assert edited["fabric"]["material"] == "醋酸"
    assert edited["fabric"]["material_en"] == "Acetate"  # 按受控词表回填
    assert updated["note"] == "面料要更挺括一点"
    # 只改属性不应丢掉小样
    assert updated["swatch"]["url"] == card["swatch"]["url"]

    # 确认 → 按卡片里的面料名检索面料图
    confirmed = _confirm(client, task_id)
    assert confirmed["status"] == TaskStatus.AWAIT_DESIGN_IDEA
    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] == TaskStatus.AWAIT_DESIGN_IDEA
    assert len(detail["material_images"]) == 3  # 1 个面料锚 × 每锚 3 张
    assert {m["label"] for m in detail["material_images"]} == {"醋酸"}
    assert all(m["origin"] == "search" for m in detail["material_images"])

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
    prompt = detail["design_images"][0]["prompt"]
    assert DESIGN_IDEA in prompt
    # 卡片编译出的材质要求（含用户备注）应进 prompt
    assert "醋酸" in prompt
    assert "面料要更挺括一点" in prompt

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

    _confirm(client, task_id)

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

    _confirm(client, task_id)

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


def test_generate_again_from_done(client, sample_clothing_image_id) -> None:
    """DONE 之后再点「再生成一版」应允许（DONE → GENERATING），且替换旧候选。"""
    task = _create_task(client, sample_clothing_image_id)
    task_id = task["id"]

    _confirm(client, task_id)

    first = client.post(
        f"/api/tasks/{task_id}/generate",
        json={"design_idea": DESIGN_IDEA, "num_candidates": 2},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == TaskStatus.DONE

    again = client.post(
        f"/api/tasks/{task_id}/generate",
        json={"design_idea": f"{DESIGN_IDEA}，袖子改短", "num_candidates": 3},
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["status"] == TaskStatus.DONE
    assert len(body["design_images"]) == 3  # 换一版：替换而不是累加


def test_generate_conflict_detail_names_current_status(
    client, sample_clothing_image_id
) -> None:
    """非法时机的 409 要带上当前状态，前端才能提示「正在生成中」之类的信息。"""
    task = _create_task(client, sample_clothing_image_id)
    current = client.get(f"/api/tasks/{task['id']}").json()["status"]

    resp = client.post(
        f"/api/tasks/{task['id']}/generate",
        json={"design_idea": "x", "num_candidates": 1},
    )
    assert resp.status_code == 409
    assert current in resp.json()["detail"]


class _NoopDispatcher:
    """只记录派发、不真正执行 —— 用来验证「接口自己先落状态」。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def dispatch_identify(self, task_id: str) -> None:
        self.calls.append("identify")

    def dispatch_material_search(self, task_id: str) -> None:
        self.calls.append("material_search")

    def dispatch_generate(
        self,
        task_id: str,
        design_idea: str | None = None,
        num_candidates: int | None = None,
    ) -> None:
        self.calls.append("generate")


def _override_dispatcher(noop: _NoopDispatcher):
    """把 dispatcher 换成不执行的版本，模拟 inline 的「异步派发」。"""
    from app.api import tasks as tasks_api
    from app.main import app

    app.dependency_overrides[tasks_api.get_dispatcher] = lambda: noop
    return app, tasks_api


def test_generate_reports_generating_before_background_runs(
    client, sample_clothing_image_id
) -> None:
    """派发是异步的：接口必须先把状态落成 GENERATING 再返回。

    否则响应带旧状态（DONE）回去，前端以为「再生成一版」还能点，再点就 409。
    """
    task = _create_task(client, sample_clothing_image_id)
    task_id = task["id"]
    _confirm(client, task_id)

    noop = _NoopDispatcher()
    app, tasks_api = _override_dispatcher(noop)
    try:
        resp = client.post(
            f"/api/tasks/{task_id}/generate",
            json={"design_idea": DESIGN_IDEA, "num_candidates": 2},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == TaskStatus.GENERATING
        assert noop.calls == ["generate"]
    finally:
        app.dependency_overrides.pop(tasks_api.get_dispatcher, None)


def test_confirm_materials_reports_searching_before_background_runs(
    client, sample_clothing_image_id
) -> None:
    task = _create_task(client, sample_clothing_image_id)
    task_id = task["id"]

    noop = _NoopDispatcher()
    app, tasks_api = _override_dispatcher(noop)
    try:
        resp = client.post(f"/api/tasks/{task_id}/confirm-materials")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == TaskStatus.MATERIAL_SEARCH
        assert noop.calls == ["material_search"]
    finally:
        app.dependency_overrides.pop(tasks_api.get_dispatcher, None)

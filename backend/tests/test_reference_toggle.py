"""「生成设计图是否参考原图」开关的端到端回归。

背景：生图时原来**无条件**把原服装图当「参考图1」交给 provider。用户希望能在
任务详情页自己决定（默认仍参考原图）。本文件覆盖：

  - 任务默认 use_reference=True（保持旧行为），列表 / 详情都会回传该字段
  - 传 use_reference=false → 编排器不再把原图交给 provider，prompt 不再声称
    「参考图1 = 原服装图」，设计图 used_reference=false，事件里有一条说明
  - 传 use_reference=true 可以再打开；**不传**则保持任务上的已有值
  - 关掉原图且没有可用材质图字节 → 实际退化成纯文生图，要提前警告
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.abilities.base import DesignImageResult, ReferenceImage
from app.abilities.prompting import NEGATIVE_PROMPT, build_design_prompt
from app.abilities.registry import register_provider, reset_abilities_cache
from app.config import apply_overrides
from app.enums import TaskStatus

DESIGN_IDEA = "改成收腰版型，裙摆加长到脚踝"

_TAGS = [
    {
        "material": "桑蚕丝",
        "material_en": "Mulberry Silk",
        "confidence": 0.9,
        "evidence": "用户确认：强光泽、细腻垂坠",
        "category": "天然纤维",
    }
]


def _png(color: tuple[int, int, int] = (20, 120, 200), size: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


class _RecordingDesignGenerator:
    """记录编排器传进来的 `reference`，并用真实 prompt 组装逻辑产出提示词。"""

    name = "recording_ref"

    def __init__(self) -> None:
        self.references: list[ReferenceImage | None] = []
        self.last_skipped_refs: list[str] = []

    def generate(
        self, material_images, design_idea, reference=None, num_candidates=3
    ) -> list[DesignImageResult]:
        self.references.append(reference)
        tags = sorted({image.tag for image in material_images if image.tag})
        # 与真实 provider 同源的组装逻辑：has_reference 决定「参考图1」是谁
        prompt = build_design_prompt(
            material_tags=tags,
            material_images_count=len(material_images),
            design_idea=design_idea,
            has_reference=reference is not None,
        )
        return [
            DesignImageResult(
                content_type="image/png",
                image_bytes=_png((10 + index * 20, 60, 90)),
                prompt=prompt,
                negative_prompt=NEGATIVE_PROMPT,
                model="recording_ref",
                seed=index,
                rank=index,
                used_reference=reference is not None,
            )
            for index in range(max(1, num_candidates))
        ]


_generators: list[_RecordingDesignGenerator] = []


def _recording_factory(ability, settings) -> _RecordingDesignGenerator:
    generator = _RecordingDesignGenerator()
    _generators.append(generator)
    return generator


register_provider("design_generator", "recording_ref", _recording_factory)


@pytest.fixture(autouse=True)
def _clean_generators():
    _generators.clear()
    yield
    _generators.clear()


def _use_recording_generator() -> None:
    """其余三个能力保持 fake（apply_overrides 是整体替换）。"""
    apply_overrides(
        {
            "clothing_search_provider": "fake",
            "material_identifier_provider": "fake",
            "material_search_provider": "fake",
            "design_generator_provider": "recording_ref",
        }
    )
    reset_abilities_cache()


def _last_references() -> list[ReferenceImage | None]:
    assert _generators, "生图 provider 没有被构建"
    return _generators[-1].references


def _task_ready_to_generate(
    client, clothing_image_id: str, *, require_material_selection: bool = False
) -> str:
    """建任务 → 确认材质 → 停在 AWAIT_DESIGN_IDEA。"""
    resp = client.post(
        "/api/tasks",
        json={
            "clothing_image_ids": [clothing_image_id],
            "require_material_selection": require_material_selection,
        },
    )
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["tasks"][0]["id"]

    resp = client.post(f"/api/tasks/{task_id}/confirm-materials", json={"tags": _TAGS})
    assert resp.status_code == 200, resp.text
    detail = client.get(f"/api/tasks/{task_id}").json()
    if not require_material_selection:
        assert detail["status"] == TaskStatus.AWAIT_DESIGN_IDEA
    return task_id


def _generate(client, task_id: str, **extra) -> dict:
    payload: dict = {"design_idea": DESIGN_IDEA, "num_candidates": 1}
    payload.update(extra)
    resp = client.post(f"/api/tasks/{task_id}/generate", json=payload)
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/tasks/{task_id}").json()


def _messages(detail: dict) -> list[str]:
    return [event["message"] for event in detail["events"]]


# --------------------------------------------------------------------------- #
# 默认：保持旧行为
# --------------------------------------------------------------------------- #
def test_new_task_references_original_image_by_default(
    client, sample_clothing_image_id
) -> None:
    _use_recording_generator()
    task_id = _task_ready_to_generate(client, sample_clothing_image_id)

    assert client.get(f"/api/tasks/{task_id}").json()["use_reference"] is True
    # 看板列表也要带该字段，前端才能在详情页把开关初值显示正确
    summary = next(
        item for item in client.get("/api/tasks").json() if item["id"] == task_id
    )
    assert summary["use_reference"] is True

    detail = _generate(client, task_id)
    assert detail["status"] == TaskStatus.DONE
    assert detail["use_reference"] is True
    assert [image["used_reference"] for image in detail["design_images"]] == [True]
    assert (
        "参考图1 = 原服装图（款式 / 版型参考）。"
        in detail["design_images"][0]["prompt"]
    )
    assert _last_references()[0] is not None


# --------------------------------------------------------------------------- #
# 关闭：原图不参与生图
# --------------------------------------------------------------------------- #
def test_disabling_reference_drops_original_image(
    client, sample_clothing_image_id
) -> None:
    _use_recording_generator()
    task_id = _task_ready_to_generate(client, sample_clothing_image_id)

    detail = _generate(client, task_id, use_reference=False)

    assert detail["use_reference"] is False
    assert detail["status"] == TaskStatus.DONE
    # provider 收到的是 None（不是「有外链的原图」）
    assert _last_references() == [None]

    prompt = detail["design_images"][0]["prompt"]
    assert "原服装图" not in prompt
    # 材质图编号从 1 开始（原图不占 1 号位）
    first_line = prompt.splitlines()[0]
    assert first_line.startswith("参考图1")
    assert "识别出的材质图" in first_line
    assert [image["used_reference"] for image in detail["design_images"]] == [False]

    assert any("不参考原服装图" in message for message in _messages(detail))


# --------------------------------------------------------------------------- #
# 反复切换 / 部分更新语义
# --------------------------------------------------------------------------- #
def test_reference_can_be_turned_back_on(client, sample_clothing_image_id) -> None:
    _use_recording_generator()
    task_id = _task_ready_to_generate(client, sample_clothing_image_id)

    _generate(client, task_id, use_reference=False)
    detail = _generate(client, task_id, use_reference=True)

    assert detail["use_reference"] is True
    assert detail["design_images"][0]["used_reference"] is True
    assert "原服装图" in detail["design_images"][0]["prompt"]
    references = _last_references()
    assert references[0] is None and references[-1] is not None


def test_omitting_flag_keeps_task_value(client, sample_clothing_image_id) -> None:
    """不传 use_reference（None）→ 保持任务上的已有值，不会被重置回默认 True。"""
    _use_recording_generator()
    task_id = _task_ready_to_generate(client, sample_clothing_image_id)

    _generate(client, task_id, use_reference=False)
    detail = _generate(client, task_id)

    assert detail["use_reference"] is False
    assert detail["design_images"][0]["used_reference"] is False
    assert _last_references()[-1] is None


# --------------------------------------------------------------------------- #
# 零参考图：退化为纯文生图，必须让用户看得见
# --------------------------------------------------------------------------- #
def test_zero_reference_warns_about_text_to_image(
    client, sample_clothing_image_id
) -> None:
    _use_recording_generator()
    task_id = _task_ready_to_generate(
        client, sample_clothing_image_id, require_material_selection=True
    )

    # 一张材质图都不选
    resp = client.post(
        f"/api/tasks/{task_id}/select-materials", json={"material_image_ids": []}
    )
    assert resp.status_code == 200, resp.text

    detail = _generate(client, task_id, use_reference=False)

    assert detail["status"] == TaskStatus.DONE
    assert detail["material_images"] != []
    assert all(not image["selected"] for image in detail["material_images"])
    assert any("纯文生图" in message for message in _messages(detail))

"""外链型材质图（只有 URL、没有本地字节）在生图链路上的回归测试。

背景：`unsplash` 等图库 provider 走热链，落库时 `storage_key` 为空、`image_bytes`
拿不到；而 `comfyui` 只能吃「上传的字节」。本文件覆盖两件事：

- Plan A：编排器在生图前**按需下载**外链参考图 → provider 能拿到字节
- Plan D：参考图确实被丢弃时，任务事件里能看到「未生效」，而不是静默降级
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.abilities.base import DesignImageResult, MaterialImageResult, MaterialQuery
from app.abilities.registry import register_provider, reset_abilities_cache
from app.config import apply_overrides
from app.enums import TaskStatus
from app.tasks import orchestrator

DESIGN_IDEA = "改成收腰版型，裙摆加长到脚踝"


def _png(color: tuple[int, int, int] = (20, 120, 200), size: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buffer, format="PNG")
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# 测试专用 provider：一个只给外链的材质检索 + 一个会记录入参的生图实现
# --------------------------------------------------------------------------- #
class _ExternalMaterialSearch:
    """模拟 Unsplash：只给外链、不给字节（→ 落库 storage_key 为空）。"""

    name = "external"
    sites = [{"id": "external", "label": "外部图库（仅外链）"}]

    def search(
        self, queries: list[MaterialQuery], per_tag: int = 3
    ) -> list[MaterialImageResult]:
        results: list[MaterialImageResult] = []
        rank = 0
        for query in queries:
            for index in range(per_tag):
                results.append(
                    MaterialImageResult(
                        label=query.material,
                        similarity=round(0.9 - 0.05 * index, 2),
                        content_type="image/jpeg",
                        external_url=(
                            f"https://cdn.example.com/{query.material}/{index}.jpg"
                        ),
                        source_url="https://cdn.example.com/photo/1",
                        rank=rank,
                    )
                )
                rank += 1
        return results


class _RecordingGenerator:
    """记录收到的参考图；像真实 provider 一样自报「被丢弃的参考图」。"""

    name = "recording"

    def __init__(self) -> None:
        self.material_images: list[MaterialImageResult] = []
        self.last_skipped_refs: list[str] = []

    def generate(
        self,
        material_images,
        design_idea,
        reference=None,
        num_candidates=3,
        material_summary="",
    ) -> list[DesignImageResult]:
        self.material_images = list(material_images)
        self.last_skipped_refs = [
            f"材质图({image.label})（测试注入：无字节，已丢弃）"
            for image in material_images
            if not image.image_bytes
        ]
        return [
            DesignImageResult(
                content_type="image/png",
                image_bytes=_png((index * 20 % 255, 60, 90)),
                prompt=f"stub:{design_idea}",
                model="recording",
                rank=index,
            )
            for index in range(max(1, num_candidates))
        ]


_generators: list[_RecordingGenerator] = []

register_provider(
    "material_search",
    "external",
    lambda ability, settings: _ExternalMaterialSearch(),
)


def _recording_factory(ability, settings) -> _RecordingGenerator:
    generator = _RecordingGenerator()
    _generators.append(generator)
    return generator


register_provider("design_generator", "recording", _recording_factory)


@pytest.fixture(autouse=True)
def _clean_generators():
    _generators.clear()
    yield
    _generators.clear()


def _use_external_material_and_recording_generator() -> None:
    """其余两个能力保持 fake（apply_overrides 是整体替换）。"""
    apply_overrides(
        {
            "clothing_search_provider": "fake",
            "material_identifier_provider": "fake",
            "material_search_provider": "external",
            "design_generator_provider": "recording",
        }
    )
    reset_abilities_cache()


def _run_pipeline(client, clothing_image_id: str) -> str:
    resp = client.post("/api/tasks", json={"clothing_image_ids": [clothing_image_id]})
    assert resp.status_code == 201, resp.text
    task_id = resp.json()["tasks"][0]["id"]

    resp = client.post(f"/api/tasks/{task_id}/confirm-materials")
    assert resp.status_code == 200, resp.text

    resp = client.post(
        f"/api/tasks/{task_id}/generate",
        json={"design_idea": DESIGN_IDEA, "num_candidates": 1},
    )
    assert resp.status_code == 200, resp.text
    return task_id


# --------------------------------------------------------------------------- #
# Plan A：生图前按需下载外链参考图，补齐字节
# --------------------------------------------------------------------------- #
def test_external_material_refs_get_bytes_before_generate(
    client, sample_clothing_image_id, monkeypatch
) -> None:
    _use_external_material_and_recording_generator()

    downloaded: list[str] = []

    def fake_fetch(url: str, **kwargs):
        downloaded.append(url)
        return _png(), "image/jpeg"

    monkeypatch.setattr(orchestrator, "fetch_image_bytes", fake_fetch)

    _run_pipeline(client, sample_clothing_image_id)

    assert downloaded, "应当按需下载外链材质图"
    assert all(url.startswith("https://cdn.example.com/") for url in downloaded)

    generator = _generators[-1]
    assert generator.material_images
    assert all(image.image_bytes for image in generator.material_images)
    assert generator.last_skipped_refs == []


def test_external_clothing_reference_also_gets_bytes(
    client, sample_clothing_image_id, monkeypatch
) -> None:
    """原服装图同样来自外链时也不应丢字节（回归 `_load_source_image` 行为）。"""
    _use_external_material_and_recording_generator()

    monkeypatch.setattr(
        orchestrator,
        "fetch_image_bytes",
        lambda url, **kwargs: (_png(), "image/jpeg"),
    )

    _run_pipeline(client, sample_clothing_image_id)

    generator = _generators[-1]
    assert generator.material_images
    assert all(image.image_bytes for image in generator.material_images)


# --------------------------------------------------------------------------- #
# Plan D：丢弃要可见（转成任务事件），且不阻断任务
# --------------------------------------------------------------------------- #
def test_dropped_refs_surface_as_task_event(
    client, sample_clothing_image_id, monkeypatch
) -> None:
    _use_external_material_and_recording_generator()

    def boom(url: str, **kwargs):
        raise RuntimeError("下载失败（测试注入）")

    monkeypatch.setattr(orchestrator, "fetch_image_bytes", boom)

    task_id = _run_pipeline(client, sample_clothing_image_id)

    detail = client.get(f"/api/tasks/{task_id}").json()
    # 参考图丢失不应让任务失败
    assert detail["status"] == TaskStatus.DONE

    # 面料名来自 fake 识别器（随图片哈希变化），所以从卡片里取而不是写死
    material = detail["material_card"]["regions"][0]["fabric"]["material"]
    messages = [event["message"] for event in detail["events"]]
    assert any("未生效" in message for message in messages), messages
    assert any(material in message for message in messages), messages

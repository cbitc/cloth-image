"""识别结果缓存测试。

缓存的价值：重复用同一张图建任务时，省掉一次 VLM 调用（实测约 1500 tokens）。
缓存的是卡片的**语义部分**（含各区域的裁剪框），小样字节不缓存 —— 命中后
由编排器拿原图按框重裁（见下面最后一个用例）。
"""

from __future__ import annotations

from app.abilities.base import (
    Abilities,
    ColorInfo,
    FabricInfo,
    MaterialCardResult,
    MaterialRegionResult,
    OpticalInfo,
    PatternInfo,
    RegionConfidence,
)
from app.db.models import ClothingImage, IdentifyCache, Task
from app.db.session import SessionLocal
from app.tasks import cache
from fakes import (
    FakeClothingSearchProvider,
    FakeDesignGenerator,
    FakeMaterialImageSearchProvider,
)


def _card(material: str = "桑蚕丝", *, regions: int = 1) -> MaterialCardResult:
    built: list[MaterialRegionResult] = []
    for index in range(regions):
        built.append(
            MaterialRegionResult(
                region_id="body" if index == 0 else f"region{index}",
                region_type="身片",
                color=ColorInfo(
                    dominant_hex="#2B3A4A",
                    dominant_name="深灰蓝",
                    lab=(35.0, -2.0, -12.0),
                    palette=[
                        {"hex": "#2B3A4A", "ratio": 0.72},
                        {"hex": "#C8C2B8", "ratio": 0.28},
                    ],
                    distribution="整体均匀",
                ),
                pattern=PatternInfo(type="纯色", layout="全身"),
                optical=OpticalInfo(gloss="哑光", transparency="不透明"),
                fabric=FabricInfo(
                    material=material,
                    material_en="Mulberry Silk",
                    category="天然纤维",
                    confidence=0.86,
                ),
                confidence=RegionConfidence(color=0.95, pattern=0.9, gloss=0.8),
                swatch_crop_box=(0.2, 0.2, 0.8, 0.8),
                swatch_content_type="image/jpeg",
            )
        )
    return MaterialCardResult(
        category="连衣裙",
        regions=built,
        evidence="强光泽、细腻垂坠",
        overall_confidence=0.8833,
    )


def _clean(db) -> None:
    cache.clear(db)


def test_store_then_lookup_roundtrip() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-a", "qwen3-vl-plus", _card(), total_tokens=1537)

        card, saved = cache.lookup(db, "hash-a", "qwen3-vl-plus")

        assert saved == 1537
        assert card is not None
        assert card.category == "连衣裙"
        region = card.primary
        assert region is not None
        assert region.color.dominant_hex == "#2B3A4A"
        assert region.color.palette[1]["hex"] == "#C8C2B8"
        assert region.pattern.type == "纯色"
        assert region.optical.gloss == "哑光"
        assert region.fabric.material == "桑蚕丝"
        assert region.fabric.category == "天然纤维"
        assert region.confidence.color == 0.95
        assert region.swatch_crop_box == (0.2, 0.2, 0.8, 0.8)
        # 小样字节不进缓存（JSON 装不下），命中后由编排器重裁
        assert region.swatch_bytes is None


def test_lookup_miss_returns_none() -> None:
    with SessionLocal() as db:
        _clean(db)
        card, saved = cache.lookup(db, "unknown-hash", "qwen3-vl-plus")
        assert card is None
        assert saved == 0


def test_model_name_is_part_of_the_key() -> None:
    """换模型后旧缓存不应串味。"""
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-b", "qwen3-vl-plus", _card(), total_tokens=100)

        hit, _ = cache.lookup(db, "hash-b", "qwen3-vl-plus")
        miss, _ = cache.lookup(db, "hash-b", "qwen-image-3.0")

        assert hit is not None and len(hit.regions) == 1
        assert miss is None


def test_hits_are_counted_and_stats_aggregate() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-c", "qwen3-vl-plus", _card(), total_tokens=1000)

        for _ in range(3):
            cache.lookup(db, "hash-c", "qwen3-vl-plus")

        report = cache.stats(db)
        assert report["entries"] == 1
        assert report["total_hits"] == 3
        assert report["saved_tokens"] == 3000  # 1000 tokens × 3 次命中
        assert report["models"] == ["qwen3-vl-plus"]


def test_store_is_idempotent_per_key() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-d", "qwen3-vl-plus", _card(regions=2), total_tokens=100)
        cache.store(db, "hash-d", "qwen3-vl-plus", _card(regions=1), total_tokens=200)

        rows = db.query(IdentifyCache).filter_by(image_hash="hash-d").all()
        assert len(rows) == 1  # 同 key 覆盖而非新增

        card, saved = cache.lookup(db, "hash-d", "qwen3-vl-plus")
        assert card is not None and len(card.regions) == 1
        assert saved == 200


def test_blank_hash_or_model_is_not_cached() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "", "qwen3-vl-plus", _card())
        cache.store(db, "hash-e", "", _card())
        cache.store(db, "hash-e2", "qwen3-vl-plus", MaterialCardResult())
        assert cache.stats(db)["entries"] == 0


def test_clear_can_target_a_single_model() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-f", "qwen3-vl-plus", _card())
        cache.store(db, "hash-g", "other-model", _card())

        removed = cache.clear(db, model="qwen3-vl-plus")

        assert removed == 1
        assert cache.lookup(db, "hash-f", "qwen3-vl-plus")[0] is None
        assert cache.lookup(db, "hash-g", "other-model")[0] is not None


def test_corrupted_payload_is_dropped() -> None:
    """旧版缓存存的是 tag 列表，与卡片结构不兼容 → 应当被丢弃而不是当成空卡片。"""
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-h", "qwen3-vl-plus", _card())
        row = db.query(IdentifyCache).filter_by(image_hash="hash-h").one()
        row.payload = [{"material": "桑蚕丝", "confidence": 0.8}]
        db.commit()

        card, saved = cache.lookup(db, "hash-h", "qwen3-vl-plus")

        assert card is None and saved == 0
        assert db.query(IdentifyCache).filter_by(image_hash="hash-h").count() == 0


def test_payload_roundtrip_helpers() -> None:
    from app.abilities.material_identify.card_normalize import (
        from_payload,
        to_payload,
    )

    payload = to_payload(_card())
    assert payload["category"] == "连衣裙"
    assert payload["regions"][0]["fabric"]["material"] == "桑蚕丝"
    restored = from_payload(payload)
    assert restored.primary is not None
    assert restored.primary.fabric.material == "桑蚕丝"
    assert from_payload("garbage").regions == []
    assert from_payload({"category": "连衣裙"}).regions == []


# --------------------------------------------------------------------------- #
# 与编排器的集成：同一张图建两个任务，第二次应命中缓存、不再调用模型
# --------------------------------------------------------------------------- #
class _CountingIdentifier:
    """计数用的假识别器：返回一张确定性卡片，并记账调用次数与 token。"""

    name = "counting"
    model = "counting-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.last_usage: dict | None = None

    def identify(
        self,
        image_bytes: bytes | None = None,
        content_type: str = "image/png",
        image_url: str = "",
        context_title: str = "",
    ) -> MaterialCardResult:
        self.calls += 1
        self.last_usage = {"total_tokens": 1234}
        return _card()


def _make_clothing(db, seed: str) -> ClothingImage:
    from app.tasks.persist import persist_bytes
    from fakes.placeholder_images import KIND_CLOTHING, make_image

    persisted = persist_bytes(
        "clothing",
        make_image(seed=seed, label="CACHE", kind=KIND_CLOTHING),
        "image/png",
    )
    row = ClothingImage(
        image_url=persisted.image_url,
        thumbnail_url=persisted.thumbnail_url,
        storage_key=persisted.storage_key,
        image_hash=persisted.image_hash,
        title="缓存集成测试",
        site="test",
        provider="fake",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_second_task_reuses_cache_without_calling_model(monkeypatch) -> None:
    from app.tasks import orchestrator

    stub = _CountingIdentifier()

    def fake_get_abilities() -> Abilities:
        return Abilities(
            clothing_search=FakeClothingSearchProvider(),
            material_identifier=stub,
            material_search=FakeMaterialImageSearchProvider(),
            design_generator=FakeDesignGenerator(),
            providers={},
        )

    monkeypatch.setattr(orchestrator, "get_abilities", fake_get_abilities)

    with SessionLocal() as db:
        cache.clear(db)
        clothing = _make_clothing(db, seed="cache-integration-1")
        first_id = orchestrator.create_tasks(db, [clothing.id])[0].id
        second_id = orchestrator.create_tasks(db, [clothing.id])[0].id

    orchestrator.run_identify(first_id)
    orchestrator.run_identify(second_id)

    with SessionLocal() as db:
        first = db.get(Task, first_id)
        second = db.get(Task, second_id)
        assert first is not None and second is not None

        assert stub.calls == 1  # 关键：第二次没有再调模型
        for task in (first, second):
            assert task.material_card is not None
            payload = task.material_card.payload
            assert payload["regions"][0]["fabric"]["material"] == "桑蚕丝"

        # 缓存命中后小样应由原图重裁并落盘（缓存里只有裁剪框）
        assert second.material_card is not None
        assert second.material_card.swatch_url
        assert second.material_card.swatch_storage_key

        messages = [event.message for event in second.events]
        assert any("命中识别缓存" in message for message in messages)
        assert any("1234" in message for message in messages)  # 展示省下的 token

        report = cache.stats(db)
        assert report["total_hits"] >= 1
        assert report["saved_tokens"] >= 1234

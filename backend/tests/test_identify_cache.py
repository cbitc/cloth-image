"""识别结果缓存测试。

缓存的价值：重复用同一张图建任务时，省掉一次 VLM 调用（实测约 1500 tokens）。
"""

from __future__ import annotations

from app.abilities.base import Abilities, MaterialTagResult
from app.db.models import ClothingImage, IdentifyCache, Task
from app.db.session import SessionLocal
from app.tasks import cache
from fakes import (
    FakeClothingSearchProvider,
    FakeDesignGenerator,
    FakeMaterialImageSearchProvider,
)

TAGS = [
    MaterialTagResult(
        material="桑蚕丝",
        material_en="Mulberry Silk",
        confidence=0.86,
        evidence="强光泽、细腻垂坠",
        category="天然纤维",
        rank=0,
    ),
    MaterialTagResult(
        material="醋酸",
        material_en="Acetate",
        confidence=0.61,
        evidence="光泽强但偏硬",
        category="再生纤维",
        rank=1,
    ),
]


def _clean(db) -> None:
    cache.clear(db)


def test_store_then_lookup_roundtrip() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-a", "qwen3-vl-plus", TAGS, total_tokens=1537)

        tags, saved = cache.lookup(db, "hash-a", "qwen3-vl-plus")

        assert saved == 1537
        assert [tag.material for tag in tags] == ["桑蚕丝", "醋酸"]
        assert tags[0].material_en == "Mulberry Silk"
        assert tags[0].confidence == 0.86
        assert tags[0].evidence == "强光泽、细腻垂坠"
        assert tags[0].category == "天然纤维"
        assert [tag.rank for tag in tags] == [0, 1]


def test_lookup_miss_returns_empty() -> None:
    with SessionLocal() as db:
        _clean(db)
        tags, saved = cache.lookup(db, "unknown-hash", "qwen3-vl-plus")
        assert tags == []
        assert saved == 0


def test_model_name_is_part_of_the_key() -> None:
    """换模型后旧缓存不应串味。"""
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-b", "qwen3-vl-plus", TAGS, total_tokens=100)

        hit, _ = cache.lookup(db, "hash-b", "qwen3-vl-plus")
        miss, _ = cache.lookup(db, "hash-b", "qwen-image-3.0")

        assert len(hit) == 2
        assert miss == []


def test_hits_are_counted_and_stats_aggregate() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-c", "qwen3-vl-plus", TAGS, total_tokens=1000)

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
        cache.store(db, "hash-d", "qwen3-vl-plus", TAGS, total_tokens=100)
        cache.store(db, "hash-d", "qwen3-vl-plus", TAGS[:1], total_tokens=200)

        rows = db.query(IdentifyCache).filter_by(image_hash="hash-d").all()
        assert len(rows) == 1  # 同 key 覆盖而非新增

        tags, saved = cache.lookup(db, "hash-d", "qwen3-vl-plus")
        assert len(tags) == 1
        assert saved == 200


def test_blank_hash_or_model_is_not_cached() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "", "qwen3-vl-plus", TAGS)
        cache.store(db, "hash-e", "", TAGS)
        assert cache.stats(db)["entries"] == 0


def test_clear_can_target_a_single_model() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-f", "qwen3-vl-plus", TAGS)
        cache.store(db, "hash-g", "other-model", TAGS)

        removed = cache.clear(db, model="qwen3-vl-plus")

        assert removed == 1
        assert cache.lookup(db, "hash-f", "qwen3-vl-plus")[0] == []
        assert cache.lookup(db, "hash-g", "other-model")[0] != []


def test_corrupted_payload_is_dropped() -> None:
    with SessionLocal() as db:
        _clean(db)
        cache.store(db, "hash-h", "qwen3-vl-plus", TAGS)
        row = db.query(IdentifyCache).filter_by(image_hash="hash-h").one()
        row.payload = ["not-a-dict"]
        db.commit()

        tags, saved = cache.lookup(db, "hash-h", "qwen3-vl-plus")

        assert tags == [] and saved == 0
        assert db.query(IdentifyCache).filter_by(image_hash="hash-h").count() == 0


def test_payload_roundtrip_helpers() -> None:
    payload = cache.to_payload(TAGS)
    assert payload[0]["material"] == "桑蚕丝"
    restored = cache.from_payload(payload)
    assert [tag.material for tag in restored] == ["桑蚕丝", "醋酸"]
    assert cache.from_payload("garbage") == []


# --------------------------------------------------------------------------- #
# 与编排器的集成：同一张图建两个任务，第二次应命中缓存、不再调用模型
# --------------------------------------------------------------------------- #
class _CountingIdentifier:
    """计数用的假识别器：第一次返回真标签，之后只记账。"""

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
    ) -> list[MaterialTagResult]:
        self.calls += 1
        self.last_usage = {"total_tokens": 1234}
        return list(TAGS)


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
        assert [tag.material for tag in first.material_tags] == ["桑蚕丝", "醋酸"]
        assert [tag.material for tag in second.material_tags] == ["桑蚕丝", "醋酸"]

        messages = [event.message for event in second.events]
        assert any("命中识别缓存" in message for message in messages)
        assert any("1234" in message for message in messages)  # 展示省下的 token

        report = cache.stats(db)
        assert report["total_hits"] >= 1
        assert report["saved_tokens"] >= 1234

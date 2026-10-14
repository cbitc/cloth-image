"""pytest 公共夹具：临时 SQLite + 本地存储 + 同步执行 + fake 能力。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 必须在导入 app.* 之前设置环境变量（Settings 有 lru_cache）
_TMP = Path(tempfile.mkdtemp(prefix="cloth-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(_TMP / "objects")
os.environ["TASK_EXECUTION"] = "sync"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from fakes import register_fake_providers  # noqa: E402

#: 测试默认把四个能力指向 fake（生产代码不再内置任何 mock 实现）
FAKE_PROVIDERS = {
    "clothing_search_provider": "fake",
    "material_search_provider": "fake",
    "material_identifier_provider": "fake",
    "design_generator_provider": "fake",
}

register_fake_providers()


@pytest.fixture(scope="session", autouse=True)
def _database():
    """所有测试开始前建表。

    用 autouse 而不是挂在 client 上：有些测试（如缓存单测）直接用 SessionLocal，
    不经过 TestClient，否则会建表缺失。
    """
    from app.db import models  # noqa: F401  确保模型注册
    from app.db.session import Base, engine

    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _fake_abilities():
    """每个用例前把四个能力指向 fake，避免用例间覆盖项污染。"""
    from app.abilities.registry import reset_abilities_cache
    from app.config import apply_overrides

    apply_overrides(dict(FAKE_PROVIDERS))
    reset_abilities_cache()
    yield


@pytest.fixture(scope="session")
def client(_database):
    from app import settings_store
    from app.db.session import SessionLocal
    from app.main import app

    # 能力配置的唯一来源是 DB；启动前写入 fake provider，应用启动时会加载
    with SessionLocal() as db:
        settings_store.save_patch(db, dict(FAKE_PROVIDERS))

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def sample_clothing_image_id(client) -> str:
    resp = client.post(
        "/api/search/clothing",
        json={"sites": ["fake-shop"], "query": "连衣裙", "count": 2},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["images"][0]["id"]

"""pytest 公共夹具：临时 SQLite + 本地存储 + 同步执行。"""

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
os.environ["PROVIDER_MODE"] = "mock"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

# 显式锁定四个能力都用 mock，避免本机 .env / shell 变量把测试切到真实 provider
os.environ["CLOTHING_SEARCH_PROVIDER"] = "mock"
os.environ["MATERIAL_IDENTIFIER_PROVIDER"] = "mock"
os.environ["MATERIAL_SEARCH_PROVIDER"] = "mock"
os.environ["DESIGN_GENERATOR_PROVIDER"] = "mock"
os.environ["MAAS_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.db.session import Base, engine
    from app.main import app

    Base.metadata.create_all(bind=engine)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def sample_clothing_image_id(client) -> str:
    resp = client.post(
        "/api/search/clothing",
        json={"sites": ["mock-shop"], "query": "连衣裙", "count": 2},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["images"][0]["id"]

"""登录 / 许可查询接口的测试（entitlement-api 用 httpx.MockTransport 伪造）。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

from conftest import TEST_LICENSE_SECRET


def _iso(expires_in: int) -> str:
    moment = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return moment.isoformat().replace("+00:00", "Z")


def _license(
    *,
    email: str = "a@example.com",
    expires_in: int = 3600,
    product: str = "cloth-image",
    plan: str | None = "pro",
    trial: bool = False,
    machine_id: str = "cloth-image-server",
    secret: str = TEST_LICENSE_SECRET,
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": email,
        "product": product,
        "trial": trial,
        "machineId": machine_id,
        "offline": False,
        "iss": "entitlement-api",
        "aud": "entitlement-client",
        "iat": now,
        "exp": now + expires_in,
    }
    if plan is not None:
        claims["plan"] = plan
    return jwt.encode(claims, secret, algorithm="HS256")


def _use_upstream(monkeypatch, handler) -> None:
    """把 auth 路由用到的客户端换成指向 MockTransport 的实例。"""
    from app.auth.client import EntitlementClient
    from app.config import get_settings

    fake = EntitlementClient(settings=get_settings(), transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.auth.router.get_entitlement_client", lambda: fake)


@pytest.fixture(autouse=True)
def _clean_cookies(client):
    client.cookies.clear()
    yield
    client.cookies.clear()


# --------------------------------------------------------------------------- #
# request-login
# --------------------------------------------------------------------------- #
def test_request_login_returns_expiry(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/request-login"
        assert json.loads(request.content) == {"email": "a@example.com"}
        return httpx.Response(202, json={"email": "a@example.com", "expiresAt": _iso(300)})

    _use_upstream(monkeypatch, handler)

    resp = client.post("/api/auth/request-login", json={"email": "  A@Example.com "})

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["email"] == "a@example.com"
    assert body["expires_at"]


def test_request_login_rate_limit(client, monkeypatch):
    _use_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            429,
            json={"error": {"type": "RateLimitExceeded", "message": "too soon"}},
        ),
    )

    resp = client.post("/api/auth/request-login", json={"email": "a@example.com"})

    assert resp.status_code == 429
    assert resp.json()["code"] == "RATE_LIMITED"


# --------------------------------------------------------------------------- #
# verify-login
# --------------------------------------------------------------------------- #
def test_verify_login_sets_cookie_and_me_reads_it(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/verify-login":
            return httpx.Response(200, json={"token": "session-token"})
        if request.url.path == "/licensing/licenses/obtain":
            assert request.headers["authorization"] == "Bearer session-token"
            assert json.loads(request.content) == {
                "product": "cloth-image",
                "machineId": "cloth-image-server",
            }
            return httpx.Response(
                200,
                json={
                    "token": _license(),
                    "plan": "pro",
                    "trial": False,
                    "expiresAt": _iso(86400),
                },
            )
        raise AssertionError(f"未预期的上游路径：{request.url.path}")

    _use_upstream(monkeypatch, handler)

    resp = client.post(
        "/api/auth/verify-login", json={"email": "a@example.com", "code": "123456"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "a@example.com"
    assert resp.json()["plan"] == "pro"
    assert resp.json()["trial"] is False
    assert client.cookies.get("ci_license")

    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["authenticated"] is True
    assert me.json()["email"] == "a@example.com"


def test_verify_login_wrong_code(client, monkeypatch):
    _use_upstream(
        monkeypatch,
        lambda request: httpx.Response(
            401, json={"error": {"type": "AuthFailed", "message": "wrong"}}
        ),
    )

    resp = client.post(
        "/api/auth/verify-login", json={"email": "a@example.com", "code": "000000"}
    )

    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CODE"
    assert not client.cookies.get("ci_license")


def test_verify_login_without_subscription(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/verify-login":
            return httpx.Response(200, json={"token": "session-token"})
        return httpx.Response(
            404,
            json={"error": {"type": "NoActiveSubscription", "message": "no license"}},
        )

    _use_upstream(monkeypatch, handler)

    resp = client.post(
        "/api/auth/verify-login", json={"email": "a@example.com", "code": "123456"}
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "SUBSCRIPTION_REQUIRED"
    assert not client.cookies.get("ci_license")


# --------------------------------------------------------------------------- #
# me
# --------------------------------------------------------------------------- #
def test_me_requires_cookie(client):
    resp = client.get("/api/auth/me")

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_me_rejects_expired_license(client):
    client.cookies.set("ci_license", _license(expires_in=-7200))

    resp = client.get("/api/auth/me")

    assert resp.status_code == 401


def test_me_rejects_other_product(client):
    client.cookies.set("ci_license", _license(product="other-product"))

    resp = client.get("/api/auth/me")

    assert resp.status_code == 401


def test_me_rejects_forged_signature(client):
    client.cookies.set(
        "ci_license", _license(secret="another-secret-at-least-32-characters-long")
    )

    resp = client.get("/api/auth/me")

    assert resp.status_code == 401


def test_me_accepts_legacy_edition_claim(client):
    """旧版签发方用 edition 而不是 plan，仍需可用。"""
    now = int(time.time())
    legacy = jwt.encode(
        {
            "sub": "a@example.com",
            "product": "cloth-image",
            "edition": "pro",
            "machineId": "cloth-image-server",
            "offline": False,
            "iss": "entitlement-api",
            "aud": "entitlement-client",
            "iat": now,
            "exp": now + 3600,
        },
        TEST_LICENSE_SECRET,
        algorithm="HS256",
    )
    client.cookies.set("ci_license", legacy)

    resp = client.get("/api/auth/me")

    assert resp.status_code == 200, resp.text
    assert resp.json()["plan"] == "pro"


def test_me_rejects_token_without_plan(client):
    client.cookies.set("ci_license", _license(plan=None))

    resp = client.get("/api/auth/me")

    assert resp.status_code == 401


def test_me_rejects_unexpected_plan_when_configured(client, monkeypatch):
    from app.config import apply_overrides, get_settings

    apply_overrides({"entitlement_plan_code": "ultimate"})
    client.cookies.set("ci_license", _license(plan="pro"))
    try:
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
    finally:
        apply_overrides({})
        get_settings.cache_clear()


def test_logout_clears_cookie(client):
    client.cookies.set("ci_license", _license(), domain="testserver", path="/")

    resp = client.post("/api/auth/logout")

    assert resp.status_code == 204
    assert "Max-Age=0" in resp.headers["set-cookie"]
    # 浏览器已经拿不到有效登录取证：后续请求视为未登录
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------- #
# 上游不可达
# --------------------------------------------------------------------------- #
def test_upstream_unreachable(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _use_upstream(monkeypatch, handler)

    resp = client.post("/api/auth/request-login", json={"email": "a@example.com"})

    assert resp.status_code == 502
    assert resp.json()["code"] == "ENTITLEMENT_UNAVAILABLE"

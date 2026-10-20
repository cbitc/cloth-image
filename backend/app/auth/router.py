"""登录与许可查询：只做「登录 + 查询有效许可」，不拦截任何业务接口。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.auth.client import EntitlementError, get_entitlement_client
from app.auth.tokens import LicenseConfigError, LicenseError, verify_license
from app.config import get_settings
from app.schemas import (
    AuthStatusOut,
    RequestLoginRequest,
    RequestLoginResponse,
    VerifyLoginRequest,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _error(status: int, code: str, detail: str) -> JSONResponse:
    """与业务接口一致的 ``{"detail": ...}``，另加机器可读的 ``code``。"""
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


def _unauthorized() -> JSONResponse:
    return _error(401, "UNAUTHENTICATED", "未登录或登录已过期")


@router.post("/request-login", response_model=RequestLoginResponse, status_code=202)
def request_login(payload: RequestLoginRequest):
    """申请邮箱验证码（有效期 5 分钟，同一邮箱 5 分钟内只能申请一次）。"""
    email = payload.email.strip().lower()
    try:
        expires_at = get_entitlement_client().request_login(email)
    except EntitlementError as exc:
        return _error(exc.status, exc.code, exc.detail)
    return RequestLoginResponse(email=email, expires_at=expires_at)


@router.post("/verify-login", response_model=AuthStatusOut)
def verify_login(payload: VerifyLoginRequest, response: Response):
    """校验验证码 → 换取许可证 → 写入 httpOnly cookie。

    会话令牌只用于换取许可证，用完即丢弃，不落库。
    """
    settings = get_settings()
    email = payload.email.strip().lower()
    client = get_entitlement_client()
    try:
        session_token = client.verify_login(email, payload.code.strip())
        grant = client.obtain_license(session_token)
    except EntitlementError as exc:
        return _error(exc.status, exc.code, exc.detail)

    try:
        claims = verify_license(grant.token, settings)
    except LicenseConfigError as exc:
        return _error(500, "LICENSE_NOT_CONFIGURED", str(exc))
    except LicenseError as exc:
        return _error(502, "LICENSE_INVALID", str(exc))

    max_age = int((grant.expires_at - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=grant.token,
        max_age=max(max_age, 0),
        httponly=True,
        samesite="lax",
        secure=settings.auth_cookie_secure,
        path="/",
    )
    return AuthStatusOut(
        email=claims.email,
        product=claims.product,
        plan=claims.plan,
        trial=claims.trial,
        expires_at=claims.expires_at,
    )


@router.get("/me", response_model=AuthStatusOut)
def me(request: Request):
    """查询当前登录状态与许可证有效期（本地验签，不请求 entitlement-api）。"""
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        return _unauthorized()

    try:
        claims = verify_license(token, settings)
    except LicenseConfigError as exc:
        return _error(500, "LICENSE_NOT_CONFIGURED", str(exc))
    except LicenseError:
        return _unauthorized()

    return AuthStatusOut(
        email=claims.email,
        product=claims.product,
        plan=claims.plan,
        trial=claims.trial,
        expires_at=claims.expires_at,
    )


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.auth_cookie_name, path="/")

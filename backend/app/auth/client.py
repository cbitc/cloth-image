"""entitlement-api-new 客户端：申请验证码 / 校验验证码 / 换取许可证。

只实现「登录 + 查询有效许可」需要的三个调用，目录、计费、设备解绑均不涉及。
上游的错误信封是 ``{"error": {"type", "message"}}``，这里统一翻译成本项目的
``(HTTP 状态码, code, 中文文案)``，让前端只认 ``code``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

#: 上游 (状态码, error.type) → 本地 (状态码, code, 文案)
_ERROR_MAP: dict[tuple[int, str], tuple[int, str, str]] = {
    (400, "ValidationError"): (400, "INVALID_INPUT", "邮箱或验证码格式不正确"),
    (429, "RateLimitExceeded"): (
        429,
        "RATE_LIMITED",
        "验证码发送过于频繁，请 5 分钟后再试",
    ),
    (401, "AuthFailed"): (401, "INVALID_CODE", "验证码不正确"),
    (404, "NotFound"): (401, "INVALID_CODE", "验证码不存在，请重新获取"),
    (410, "Expired"): (410, "CODE_EXPIRED", "验证码已过期，请重新获取"),
    (429, "VerificationLimitExceeded"): (
        429,
        "TOO_MANY_ATTEMPTS",
        "验证码尝试次数过多，请重新获取",
    ),
    (401, "Unauthorized"): (401, "SESSION_EXPIRED", "登录状态已失效，请重新登录"),
    (404, "NoActiveSubscription"): (403, "SUBSCRIPTION_REQUIRED", "当前账号没有有效订阅"),
    (404, "UnknownEdition"): (404, "UNKNOWN_EDITION", "产品版本不存在"),
    (409, "EditionUnavailable"): (409, "EDITION_UNAVAILABLE", "该产品版本已下架"),
    (409, "ActivationLimitExceeded"): (409, "ACTIVATION_LIMIT", "授权设备数已达上限"),
}


class EntitlementError(Exception):
    """上游返回可识别的错误，或服务不可达。"""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class LicenseGrant:
    """``POST /licensing/licenses/obtain`` 的结果。"""

    token: str
    expires_at: datetime


def _translate(resp: httpx.Response) -> EntitlementError:
    error_type = ""
    upstream_message = ""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type") or "")
            upstream_message = str(error.get("message") or "")

    mapped = _ERROR_MAP.get((resp.status_code, error_type))
    if mapped is not None:
        return EntitlementError(*mapped)

    detail = upstream_message or f"登录服务返回 {resp.status_code}"
    status = 502 if resp.status_code >= 500 else resp.status_code
    return EntitlementError(status, "ENTITLEMENT_ERROR", detail)


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class EntitlementClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self._settings.entitlement_api_base_url.rstrip("/"),
            timeout=self._settings.entitlement_timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ #
    # 三个调用
    # ------------------------------------------------------------------ #
    def request_login(self, email: str) -> datetime:
        """申请验证码，返回验证码的过期时间。"""
        data = self._post("/auth/request-login", {"email": email})
        expires_at = _parse_iso(data.get("expiresAt"))
        return expires_at or (datetime.now(timezone.utc) + timedelta(minutes=5))

    def verify_login(self, email: str, code: str) -> str:
        """校验验证码，返回 entitlement 的会话令牌（只用于换取许可证）。"""
        data = self._post("/auth/verify-login", {"email": email, "code": code})
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise EntitlementError(502, "ENTITLEMENT_BAD_RESPONSE", "登录服务未返回会话令牌")
        return token

    def obtain_license(self, session_token: str) -> LicenseGrant:
        """用会话令牌换取许可证；无订阅时抛 403。"""
        settings = self._settings
        data = self._post(
            "/licensing/licenses/obtain",
            {
                "product": settings.entitlement_product_code,
                "edition": settings.entitlement_edition_code,
                "machineId": settings.entitlement_machine_id,
            },
            token=session_token,
        )
        token = data.get("token")
        expires_at = _parse_iso(data.get("expiresAt"))
        if not isinstance(token, str) or not token or expires_at is None:
            raise EntitlementError(502, "ENTITLEMENT_BAD_RESPONSE", "登录服务未返回有效许可证")
        return LicenseGrant(token=token, expires_at=expires_at)

    # ------------------------------------------------------------------ #
    def _post(
        self, path: str, payload: dict[str, object], token: str | None = None
    ) -> dict:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            resp = self._client.post(path, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # 只记类型：异常文本里可能带 URL，但绝不记录请求头里的令牌
            logger.warning("entitlement-api 不可达：POST %s (%s)", path, type(exc).__name__)
            raise EntitlementError(
                502, "ENTITLEMENT_UNAVAILABLE", "登录服务暂不可用，请稍后再试"
            ) from exc

        if resp.status_code >= 400:
            raise _translate(resp)

        try:
            data = resp.json()
        except ValueError as exc:
            raise EntitlementError(
                502, "ENTITLEMENT_BAD_RESPONSE", "登录服务返回了无法解析的响应"
            ) from exc
        if not isinstance(data, dict):
            raise EntitlementError(
                502, "ENTITLEMENT_BAD_RESPONSE", "登录服务返回了无法解析的响应"
            )
        return data


@lru_cache
def get_entitlement_client() -> EntitlementClient:
    return EntitlementClient()

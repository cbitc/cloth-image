"""许可证 JWT 的本地校验（HS256，不联网）。

许可证由 entitlement-api-new 用 ``LICENSE_JWT_SECRET`` 签发，
claims: ``sub``（邮箱）、``product``、``edition``、``machineId``、``offline``、``exp``。
本模块只验签 + 校验归属，不做任何网络请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import jwt

from app.config import Settings

#: 允许的时钟偏差（秒）
_LEEWAY_S = 60


class LicenseError(Exception):
    """许可证缺失、签名不符、过期或与当前部署不匹配。"""


class LicenseConfigError(LicenseError):
    """缺少验签密钥等部署配置问题（属于 500，而非 401）。"""


@dataclass(frozen=True)
class LicenseClaims:
    email: str
    product: str
    edition: str
    machine_id: str
    offline: bool
    expires_at: datetime


def verify_license(token: str, settings: Settings) -> LicenseClaims:
    secret = settings.entitlement_license_jwt_secret
    if not secret:
        raise LicenseConfigError("未配置 ENTITLEMENT_LICENSE_JWT_SECRET，无法校验许可证")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=settings.entitlement_license_audience,
            issuer=settings.entitlement_license_issuer,
            leeway=_LEEWAY_S,
            options={"require": ["exp", "sub", "product", "edition"]},
        )
    except jwt.PyJWTError as exc:
        raise LicenseError(f"许可证无效或已过期：{exc}") from exc

    email = str(payload.get("sub") or "")
    product = str(payload.get("product") or "")
    edition = str(payload.get("edition") or "")
    machine_id = str(payload.get("machineId") or "")

    if product != settings.entitlement_product_code:
        raise LicenseError(f"许可证属于产品 {product or '未知'}，不是本产品")
    if machine_id != settings.entitlement_machine_id:
        raise LicenseError("许可证绑定的设备与本服务不一致")

    expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    return LicenseClaims(
        email=email,
        product=product,
        edition=edition,
        machine_id=machine_id,
        offline=bool(payload.get("offline", False)),
        expires_at=expires_at,
    )

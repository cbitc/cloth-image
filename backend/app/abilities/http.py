"""共享 HTTP 客户端：超时、指数退避重试、统一异常层次。

所有真实 provider（VLM / 生图 / 图库）都通过它发请求，保证：

- 超时可控，不会把 worker 挂死
- 只对「值得重试」的错误重试（408/429/5xx 与连接错误）
- 失败时抛出带响应体片段的具名异常，便于日志与前端定位
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
BODY_SNIPPET = 600


class ProviderError(RuntimeError):
    """能力提供方调用失败的基类。"""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        provider: str = "",
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.provider = provider
        self.body = body


class ProviderAuthError(ProviderError):
    """401/403：Key 缺失、失效或权限不足。"""


class ProviderRateLimitError(ProviderError):
    """429：限流。"""


class ProviderBadRequestError(ProviderError):
    """4xx：请求本身有问题（参数、模型名、不支持的字段等）。"""


class ProviderTimeoutError(ProviderError):
    """请求超时且重试耗尽。"""


def build_provider_error(provider: str, status: int, body: str) -> ProviderError:
    snippet = (body or "").strip()[:BODY_SNIPPET]
    if status in (401, 403):
        cls, head = (
            ProviderAuthError,
            f"{provider} 鉴权失败（HTTP {status}），请检查 API Key",
        )
    elif status == 429:
        cls, head = ProviderRateLimitError, f"{provider} 触发限流（HTTP 429）"
    elif 400 <= status < 500:
        cls, head = ProviderBadRequestError, f"{provider} 请求被拒绝（HTTP {status}）"
    else:
        cls, head = ProviderError, f"{provider} 服务端错误（HTTP {status}）"
    message = f"{head}: {snippet}" if snippet else head
    return cls(message, status=status, provider=provider, body=snippet)


class RetryingHttpClient:
    """带重试的 JSON/二进制 HTTP 客户端。

    `client` 与 `sleep_fn` 均可注入，便于单测使用 `httpx.MockTransport`
    且不产生真实等待。
    """

    def __init__(
        self,
        *,
        provider: str = "provider",
        timeout_s: float = 90.0,
        max_retries: int = 3,
        backoff_base: float = 0.8,
        backoff_cap: float = 8.0,
        client: httpx.Client | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self._timeout_s = timeout_s
        self._max_retries = max(0, max_retries)
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep_fn = sleep_fn
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_s), follow_redirects=True
        )

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #
    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        return self._request_json(
            "POST", url, headers=headers, json_body=payload, timeout_s=timeout_s
        )

    def post_multipart(
        self,
        url: str,
        *,
        files: dict[str, tuple[str, bytes, str]],
        form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """上传文件（multipart/form-data），返回解析后的 JSON。

        用于 ComfyUI 的 `POST /upload/image` 这类接口（`json` 与 `data` 互斥）。
        `files` 形如 `{"image": ("ref.png", data, "image/png")}`。
        """
        return self._request_json(
            "POST",
            url,
            headers=headers,
            files=files,
            form=form,
            timeout_s=timeout_s,
        )

    def get_json(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        return self._request_json("GET", url, headers=headers, timeout_s=timeout_s)

    def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
        timeout_s: float | None = None,
    ) -> tuple[bytes, str]:
        """流式下载，带大小上限保护。返回 (内容, content-type)。"""
        effective_timeout = timeout_s or self._timeout_s
        try:
            with self._client.stream(
                "GET", url, headers=headers, timeout=effective_timeout
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise build_provider_error(
                        self.provider, resp.status_code, resp.text
                    )

                content_type = (
                    (resp.headers.get("content-type") or "").split(";")[0].strip()
                )

                declared = resp.headers.get("content-length")
                if (
                    max_bytes
                    and declared
                    and declared.isdigit()
                    and int(declared) > max_bytes
                ):
                    raise ProviderError(
                        f"{self.provider} 图片过大（{declared} bytes > 上限 {max_bytes}）",
                        provider=self.provider,
                    )

                buffer = bytearray()
                for chunk in resp.iter_bytes():
                    buffer.extend(chunk)
                    if max_bytes and len(buffer) > max_bytes:
                        raise ProviderError(
                            f"{self.provider} 图片超过大小上限 {max_bytes} bytes",
                            provider=self.provider,
                        )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{self.provider} 下载超时（{effective_timeout}s）",
                provider=self.provider,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.provider} 下载失败: {exc}", provider=self.provider
            ) from exc

        return bytes(buffer), content_type or "application/octet-stream"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        form: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        effective_timeout = timeout_s or self._timeout_s
        attempt = 0
        last_exc: ProviderError | None = None

        while attempt <= self._max_retries:
            attempt += 1
            try:
                request_kwargs: dict[str, Any] = {
                    "headers": headers,
                    "timeout": effective_timeout,
                }
                if files is not None:
                    request_kwargs["files"] = files
                    if form:
                        request_kwargs["data"] = form
                else:
                    request_kwargs["json"] = json_body

                response = self._client.request(method, url, **request_kwargs)
            except httpx.TimeoutException as exc:
                last_exc = ProviderTimeoutError(
                    f"{self.provider} 请求超时（{effective_timeout}s）",
                    provider=self.provider,
                )
                if attempt <= self._max_retries:
                    self._sleep(attempt)
                    continue
                raise last_exc from exc
            except httpx.HTTPError as exc:
                last_exc = ProviderError(
                    f"{self.provider} 网络错误: {exc}", provider=self.provider
                )
                if attempt <= self._max_retries:
                    self._sleep(attempt)
                    continue
                raise last_exc from exc

            if response.status_code in RETRY_STATUS and attempt <= self._max_retries:
                self._sleep(attempt, response.headers.get("Retry-After"))
                continue

            if response.status_code >= 400:
                raise build_provider_error(
                    self.provider, response.status_code, response.text
                )

            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(
                    f"{self.provider} 返回了非 JSON 响应: {response.text[:200]}",
                    status=response.status_code,
                    provider=self.provider,
                ) from exc

        raise last_exc or ProviderError(
            f"{self.provider} 调用失败（已重试 {self._max_retries} 次）",
            provider=self.provider,
        )

    def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay: float | None = None
        if retry_after:
            try:
                delay = float(retry_after)
            except (TypeError, ValueError):
                delay = None
        if delay is None:
            delay = min(self._backoff_cap, self._backoff_base * (2 ** (attempt - 1)))
            delay *= 1 + random.uniform(0, 0.25)  # 抖动，避免同时重试
        logger.warning(
            "%s 第 %d 次重试，%.2fs 后重发", self.provider, attempt, max(0.0, delay)
        )
        self._sleep_fn(max(0.0, delay))

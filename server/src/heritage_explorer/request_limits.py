"""ASGI request-size guards for public JSON endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection
import math
from typing import Any


MAX_PUBLIC_JSON_BODY_BYTES = 64 * 1024
PUBLIC_JSON_BODY_TIMEOUT_SECONDS = 10.0
PUBLIC_JSON_ROUTES = frozenset(
    {
        ("POST", "/api/chat"),
        ("POST", "/api/tts"),
    }
)


class RequestBodyLimitMiddleware:
    """Reject oversized or stalled public JSON bodies before framework decoding."""

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int = MAX_PUBLIC_JSON_BODY_BYTES,
        read_timeout: float = PUBLIC_JSON_BODY_TIMEOUT_SECONDS,
        routes: Collection[tuple[str, str]] = PUBLIC_JSON_ROUTES,
    ) -> None:
        timeout = float(read_timeout)
        if max_bytes <= 0:
            raise ValueError("request body limit must be positive")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("request body timeout must be a finite positive number")
        self.app = app
        self.max_bytes = max_bytes
        self.read_timeout = timeout
        self.routes = frozenset((method.upper(), path) for method, path in routes)

    @staticmethod
    def _content_length(scope: dict[str, Any]) -> int | None:
        for name, value in scope.get("headers", ()):
            if name.lower() != b"content-length":
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return None
            return max(0, parsed)
        return None

    @staticmethod
    async def _reject(
        send: Callable[..., Awaitable[None]],
        *,
        status: int,
        detail: str,
    ) -> None:
        body = f'{{"detail":"{detail}"}}'.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        if (method, path) not in self.routes:
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._reject(send, status=413, detail="request_body_too_large")
            return

        chunks: list[bytes] = []
        total = 0
        try:
            async with asyncio.timeout(self.read_timeout):
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        return
                    if message.get("type") != "http.request":
                        continue

                    chunk = bytes(message.get("body") or b"")
                    total += len(chunk)
                    if total > self.max_bytes:
                        await self._reject(send, status=413, detail="request_body_too_large")
                        return
                    if chunk:
                        chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self._reject(send, status=408, detail="request_body_timeout")
            return

        body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)


__all__ = [
    "MAX_PUBLIC_JSON_BODY_BYTES",
    "PUBLIC_JSON_BODY_TIMEOUT_SECONDS",
    "PUBLIC_JSON_ROUTES",
    "RequestBodyLimitMiddleware",
]

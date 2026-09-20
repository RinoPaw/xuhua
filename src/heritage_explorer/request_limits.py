"""ASGI request-size guards for public JSON endpoints."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from typing import Any


MAX_PUBLIC_JSON_BODY_BYTES = 64 * 1024
PUBLIC_JSON_ROUTES = frozenset(
    {
        ("POST", "/api/chat"),
        ("POST", "/api/tts"),
    }
)


class RequestBodyLimitMiddleware:
    """Reject oversized parsed-body routes before framework JSON decoding."""

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int = MAX_PUBLIC_JSON_BODY_BYTES,
        routes: Collection[tuple[str, str]] = PUBLIC_JSON_ROUTES,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("request body limit must be positive")
        self.app = app
        self.max_bytes = max_bytes
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
    async def _reject(send: Callable[..., Awaitable[None]]) -> None:
        body = b'{"detail":"request_body_too_large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
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
            await self._reject(send)
            return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                await self.app(scope, lambda: _constant_message(message), send)
                return
            if message.get("type") != "http.request":
                continue

            chunk = bytes(message.get("body") or b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._reject(send)
                return
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


async def _constant_message(message: dict[str, Any]) -> dict[str, Any]:
    return message


__all__ = [
    "MAX_PUBLIC_JSON_BODY_BYTES",
    "PUBLIC_JSON_ROUTES",
    "RequestBodyLimitMiddleware",
]

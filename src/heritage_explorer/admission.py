"""Shared admission budgets for expensive public endpoints."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import time
from typing import Any


WINDOW_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    """Bound one service by concurrency and rolling request budgets."""

    max_concurrency: int
    max_per_minute: int
    max_per_client_per_minute: int

    def __post_init__(self) -> None:
        if (
            self.max_concurrency <= 0
            or self.max_per_minute <= 0
            or self.max_per_client_per_minute <= 0
        ):
            raise ValueError("admission limits must be positive")
        if self.max_per_client_per_minute > self.max_per_minute:
            raise ValueError("per-client admission limit cannot exceed global limit")


class AdmissionDenied(RuntimeError):
    """A request could not enter an expensive service right now."""

    def __init__(self, service: str, reason: str, retry_after: int) -> None:
        super().__init__(reason)
        self.service = service
        self.reason = reason
        self.retry_after = max(1, int(retry_after))


class AdmissionLease:
    """One admitted request whose concurrency slot is released exactly once."""

    def __init__(self, controller: "AdmissionController", service: str) -> None:
        self._controller = controller
        self.service = service
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        # Streaming HTTP/WebSocket tasks may be cancelled while unwinding. The
        # caller's cancellation still propagates, but the shared capacity slot
        # must be returned even when that happens inside a level-cancel scope.
        await asyncio.shield(self._controller._release(self.service))

    async def __aenter__(self) -> "AdmissionLease":
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.release()


class AdmissionController:
    """Atomic admission control shared by HTTP streams and WebSocket sessions."""

    def __init__(
        self,
        policies: Mapping[str, AdmissionPolicy],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not policies:
            raise ValueError("at least one admission policy is required")
        self._policies = dict(policies)
        self._clock = clock
        self._lock = asyncio.Lock()
        self._active = {service: 0 for service in self._policies}
        self._global_usage = {service: deque() for service in self._policies}
        self._client_usage: dict[tuple[str, str], deque[float]] = {}

    @staticmethod
    def _trim(bucket: deque[float], now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    @staticmethod
    def _retry_after(bucket: deque[float], now: float) -> int:
        if not bucket:
            return 1
        return max(1, math.ceil(WINDOW_SECONDS - (now - bucket[0])))

    def _prune_clients(self, now: float) -> None:
        if len(self._client_usage) < 1024:
            return
        for key, bucket in tuple(self._client_usage.items()):
            self._trim(bucket, now)
            if not bucket:
                self._client_usage.pop(key, None)

    async def _admit(
        self,
        service: str,
        client_id: object,
        *,
        hold_concurrency: bool,
    ) -> None:
        policy = self._policies.get(service)
        if policy is None:
            raise KeyError(f"unknown admission service: {service}")
        client_key = str(client_id or "unknown").strip()[:256] or "unknown"
        now = self._clock()

        async with self._lock:
            if hold_concurrency and self._active[service] >= policy.max_concurrency:
                raise AdmissionDenied(service, "capacity", 1)

            global_bucket = self._global_usage[service]
            self._trim(global_bucket, now)
            if len(global_bucket) >= policy.max_per_minute:
                raise AdmissionDenied(
                    service,
                    "global_rate",
                    self._retry_after(global_bucket, now),
                )

            client_bucket = self._client_usage.setdefault((service, client_key), deque())
            self._trim(client_bucket, now)
            if len(client_bucket) >= policy.max_per_client_per_minute:
                raise AdmissionDenied(
                    service,
                    "client_rate",
                    self._retry_after(client_bucket, now),
                )

            global_bucket.append(now)
            client_bucket.append(now)
            if hold_concurrency:
                self._active[service] += 1
            self._prune_clients(now)

    async def acquire(self, service: str, client_id: object = "unknown") -> AdmissionLease:
        """Charge rolling-rate budgets and reserve one concurrency slot."""
        await self._admit(service, client_id, hold_concurrency=True)
        return AdmissionLease(self, service)

    async def charge(self, service: str, client_id: object = "unknown") -> None:
        """Charge rolling-rate budgets without reserving a concurrency slot."""
        await self._admit(service, client_id, hold_concurrency=False)

    async def _release(self, service: str) -> None:
        async with self._lock:
            if service in self._active:
                self._active[service] = max(0, self._active[service] - 1)


def client_key_from_scope(scope: Mapping[str, Any]) -> str:
    """Use the ASGI-resolved peer address rather than trusting raw forwarding headers."""

    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        host = str(client[0] or "").strip()
        if host:
            return host[:256]
    host = getattr(client, "host", "")
    return str(host or "unknown").strip()[:256] or "unknown"


class AdmissionMiddleware:
    """Hold expensive transport lifetimes and rate-charge cheap setup requests."""

    ROUTES = {
        ("http", "POST", "/api/chat"): "chat",
        ("websocket", "", "/api/voice"): "voice",
    }
    RATE_ONLY_ROUTES = {
        ("http", "POST", "/api/tts"): "tts_ticket",
    }

    def __init__(self, app: Any, *, controller: AdmissionController) -> None:
        self.app = app
        self.controller = controller

    @classmethod
    def route_key(cls, scope: Mapping[str, Any]) -> tuple[str, str, str]:
        scope_type = str(scope.get("type") or "")
        method = str(scope.get("method") or "").upper() if scope_type == "http" else ""
        path = str(scope.get("path") or "")
        return scope_type, method, path

    @classmethod
    def service_for_scope(cls, scope: Mapping[str, Any]) -> str | None:
        key = cls.route_key(scope)
        return cls.ROUTES.get(key) or cls.RATE_ONLY_ROUTES.get(key)

    @staticmethod
    async def reject(scope: Mapping[str, Any], send: Callable[..., Any], exc: AdmissionDenied) -> None:
        detail = f"{exc.service}_{exc.reason}"
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1013, "reason": detail})
            return

        status = 503 if exc.reason == "capacity" else 429
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"retry-after", str(exc.retry_after).encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        key = self.route_key(scope)
        service = self.service_for_scope(scope)
        if service is None:
            await self.app(scope, receive, send)
            return

        client_id = client_key_from_scope(scope)
        if key in self.RATE_ONLY_ROUTES:
            try:
                await self.controller.charge(service, client_id)
            except AdmissionDenied as exc:
                await self.reject(scope, send, exc)
                return
            await self.app(scope, receive, send)
            return

        try:
            lease = await self.controller.acquire(service, client_id)
        except AdmissionDenied as exc:
            await self.reject(scope, send, exc)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            await lease.release()


__all__ = [
    "AdmissionController",
    "AdmissionDenied",
    "AdmissionLease",
    "AdmissionMiddleware",
    "AdmissionPolicy",
    "client_key_from_scope",
]

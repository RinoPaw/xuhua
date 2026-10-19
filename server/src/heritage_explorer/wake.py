"""Authenticated, same-origin bridge to the single native wake engine."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
import hashlib
import hmac
import json
import logging
import math
import os
import time

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect

from .admission import AdmissionController, AdmissionDenied, AdmissionPolicy, client_key_from_scope
from .voice_transport import websocket_origin_allowed

LOGGER = logging.getLogger(__name__)
COOKIE = "xuhua_wake_terminal"
COOKIE_SECONDS = 30 * 86400


class Authorization(BaseModel):
    code: str = Field(min_length=16, max_length=128)


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(pattern=r"^(wake|wake_detected|conversation)$")
    outcome: str = Field(pattern=r"^(completed|failed|cancelled|interrupted|disconnected|superseded|rejected)$")
    elapsed_ms: float = Field(ge=0, le=300000, allow_inf_nan=False)
    played: bool = False
    attempt: str = Field(min_length=1, max_length=72, pattern=r"^[A-Za-z0-9_-]+$")


def register_wake_routes(app: FastAPI) -> bool:
    url = os.getenv("XF_WAKE_URL", "").strip()
    token = os.getenv("XF_WAKE_TOKEN", "").strip()
    terminal_key = os.getenv("XF_WAKE_TERMINAL_KEY", "").strip()
    enabled = bool(url and token and len(terminal_key) >= 16)
    admission = AdmissionController({
        "authorize": AdmissionPolicy(1, 30, 6),
        "wake": AdmissionPolicy(1, 90, 30),
        "metrics": AdmissionPolicy(8, 180, 90),
    })
    records: deque[tuple[float, Timing]] = deque(maxlen=2000)

    def signature(value: str) -> str:
        return hmac.new(terminal_key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def authorized(cookies: dict[str, str]) -> bool:
        try:
            expiry, mac = cookies.get(COOKIE, "").split(".", 1)
            remaining = int(expiry) - time.time()
            return enabled and 0 < remaining <= COOKIE_SECONDS and hmac.compare_digest(mac, signature(expiry))
        except (ValueError, TypeError):
            return False

    def check_origin(scope, headers):
        return websocket_origin_allowed(headers.get("origin"), headers.get("host", ""),
                                        websocket_scheme=scope.get("scheme", ""),
                                        forwarded_proto=headers.get("x-forwarded-proto", ""))

    @app.get("/api/wake/status")
    async def status(request: Request):
        return {"available": enabled, "authorized": authorized(request.cookies),
                "provider": "xfyun" if enabled else "sherpa", "keywords": ["叙华", "你好叙华"]}

    @app.post("/api/wake/authorize")
    async def authorize(request: Request, body: Authorization, response: Response):
        if not enabled:
            raise HTTPException(404, "wake_unavailable")
        if not check_origin(request.scope, request.headers):
            raise HTTPException(403, "origin_forbidden")
        try:
            await admission.charge("authorize", client_key_from_scope(request.scope))
        except AdmissionDenied as exc:
            raise HTTPException(429, "wake_rate_limited") from exc
        if not hmac.compare_digest(body.code.encode(), terminal_key.encode()):
            raise HTTPException(403, "wake_authorization_required")
        expiry = str(int(time.time()) + COOKIE_SECONDS)
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(COOKIE, expiry + "." + signature(expiry), max_age=COOKIE_SECONDS,
                            httponly=True, secure=secure, samesite="strict", path="/api/wake")
        response.headers["Cache-Control"] = "no-store"
        return {"authorized": True}

    @app.post("/api/wake/metrics", status_code=204)
    async def timing(request: Request, body: Timing):
        if not authorized(request.cookies) or not check_origin(request.scope, request.headers):
            raise HTTPException(403, "wake_authorization_required")
        try:
            await admission.charge("metrics", client_key_from_scope(request.scope))
        except AdmissionDenied as exc:
            raise HTTPException(429, "wake_rate_limited") from exc
        if not any(item.attempt == body.attempt and item.kind == body.kind for _, item in records):
            records.append((time.time(), body))
            LOGGER.info("voice.timing kind=%s outcome=%s elapsed_ms=%.1f played=%s attempt=%s",
                        body.kind, body.outcome, body.elapsed_ms, body.played, body.attempt)
        return Response(status_code=204)

    @app.get("/api/wake/metrics")
    async def metrics(request: Request):
        if not authorized(request.cookies):
            raise HTTPException(403, "wake_authorization_required")
        result = {}
        for kind in ("wake", "wake_detected", "conversation"):
            items = [item for stamp, item in records if stamp > time.time() - 86400 and item.kind == kind]
            values = sorted(item.elapsed_ms for item in items if item.played)
            def percentile(fraction):
                return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 1) if values else None
            result[kind] = {"attempts": len(items), "played": len(values), "not_played": len(items) - len(values),
                            "mean_ms": round(sum(values) / len(values), 1) if values else None,
                            "p50_ms": percentile(.5), "p95_ms": percentile(.95)}
        return {"window": "24h, at most 2000 attempts since process start", **result}

    @app.websocket("/api/wake")
    async def wake(ws: WebSocket):
        if not check_origin(ws.scope, ws.headers) or not authorized(ws.cookies):
            await ws.close(code=1008)
            return
        await ws.accept()
        lease = None
        tasks = []
        try:
            lease = await admission.acquire("wake", client_key_from_scope(ws.scope))
            async with connect(url, proxy=None, open_timeout=5, max_size=8192,
                               ping_interval=15, ping_timeout=15) as upstream:
                await upstream.send(json.dumps({"token": token}))
                first = json.loads(await asyncio.wait_for(upstream.recv(), 5))
                await ws.send_json(first)
                if first.get("type") != "ready":
                    return

                async def incoming():
                    while True:
                        message = await asyncio.wait_for(ws.receive(), 40)
                        if message["type"] == "websocket.disconnect":
                            return
                        pcm = message.get("bytes")
                        if pcm is not None:
                            if not pcm or len(pcm) > 6400 or len(pcm) % 2:
                                return
                            await upstream.send(pcm)
                        else:
                            control = json.loads(message.get("text", ""))
                            if control.get("type") not in ("ping", "pause", "resume"):
                                return
                            await upstream.send(json.dumps({"type": control["type"]}))

                async def outgoing():
                    async for raw in upstream:
                        event = json.loads(raw)
                        if event.get("type") in ("ready", "wake", "error", "paused", "pong"):
                            await ws.send_json(event)

                tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except AdmissionDenied:
            await ws.send_json({"type": "error", "code": "wake_busy"})
        except Exception:
            # Upstream URLs, handshakes and tokens must never enter client errors or logs.
            with suppress(Exception):
                await ws.send_json({"type": "error", "code": "wake_unavailable"})
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if lease:
                await lease.release()
            with suppress(Exception):
                await ws.close()
    return enabled

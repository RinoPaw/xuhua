"""WebSocket transport for typed realtime voice commands and server events."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .assistant import AssistantService
from .asr_normalization import NormalizedTranscript
from .dataset import KnowledgeBase
from .sessions import SessionStore
from .voice import VoiceProviderError, XfyunStream
from .voice_events import ReadyEvent, VoiceServerEvent, encode_voice_event
from .voice_protocol import VoiceCommand, WakeCommand, decode_voice_command
from .voice_session import VoiceSessionRuntime


MAX_VOICE_FRAME_BYTES = 64 * 1024
_ORIGIN_DEFAULT_PORTS = {"http": 80, "https": 443}


def _canonical_origin(value: str, *, fallback_scheme: str = "") -> tuple[str, str, int] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = raw if "://" in raw else f"{fallback_scheme or 'http'}://{raw}"
    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").casefold().rstrip(".")
        port = parsed.port or _ORIGIN_DEFAULT_PORTS.get(scheme, 0)
    except ValueError:
        return None
    if scheme not in _ORIGIN_DEFAULT_PORTS or not host or not port:
        return None
    return scheme, host, port


def websocket_origin_allowed(
    origin: str | None,
    host: str,
    *,
    websocket_scheme: str,
    forwarded_proto: str = "",
) -> bool:
    """Allow browser WebSockets only from the public origin serving this request.

    Browsers always send ``Origin`` for a WebSocket handshake. Non-browser
    clients may omit it, so absence remains compatible with CLI/test clients.
    When an Origin is present we require an exact scheme/host/port match with
    the externally visible request origin. Reverse proxies communicate the
    public scheme through ``X-Forwarded-Proto`` while preserving ``Host``.
    """

    if origin is None or not str(origin).strip():
        return True

    ws_scheme = str(websocket_scheme or "").casefold()
    external_scheme = str(forwarded_proto or "").split(",", 1)[0].strip().casefold()
    if external_scheme not in _ORIGIN_DEFAULT_PORTS:
        external_scheme = "https" if ws_scheme == "wss" else "http"

    actual = _canonical_origin(str(origin))
    expected = _canonical_origin(str(host), fallback_scheme=external_scheme)
    return actual is not None and expected is not None and actual == expected


class VoiceWebSocketChannel:
    """Own the wire envelope and serialized writes for one WebSocket connection."""

    def __init__(self, websocket: WebSocket, *, connection_id: str | None = None) -> None:
        self.websocket = websocket
        self.connection_id = connection_id or uuid.uuid4().hex
        self.sequence = 0
        self.send_lock = asyncio.Lock()

    async def emit(self, event: VoiceServerEvent) -> None:
        payload = encode_voice_event(event)
        try:
            async with self.send_lock:
                self.sequence += 1
                await self.websocket.send_json(
                    {
                        "connection_id": self.connection_id,
                        "sequence": self.sequence,
                        **payload,
                    }
                )
        except (RuntimeError, WebSocketDisconnect):
            pass


async def dispatch_voice_command(runtime: VoiceSessionRuntime, command: VoiceCommand) -> None:
    if isinstance(command, WakeCommand):
        await runtime.acknowledge_address()
        return
    await runtime.handle_command(command)


def _frame_too_large(message: dict[str, Any]) -> bool:
    data = message.get("bytes")
    if data is not None:
        return len(data) > MAX_VOICE_FRAME_BYTES

    raw = message.get("text")
    if raw is None:
        return False
    if len(raw) > MAX_VOICE_FRAME_BYTES:
        return True
    return len(raw.encode("utf-8")) > MAX_VOICE_FRAME_BYTES


async def run_voice_transport(
    websocket: WebSocket,
    channel: VoiceWebSocketChannel,
    runtime: VoiceSessionRuntime,
) -> None:
    """Receive bounded frames, decode commands, and delegate state to the runtime."""

    try:
        await channel.emit(ReadyEvent())
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if _frame_too_large(message):
                await websocket.close(code=1009, reason="voice_frame_too_large")
                break

            data = message.get("bytes")
            if data is not None:
                try:
                    await runtime.handle_audio(data)
                except VoiceProviderError as exc:
                    await websocket.close(code=1013, reason=str(exc)[:123])
                    break
                continue

            raw = message.get("text")
            if not raw:
                continue
            command = decode_voice_command(raw)
            if command is not None:
                await dispatch_voice_command(runtime, command)
    except WebSocketDisconnect:
        pass
    finally:
        await runtime.close()


def register_voice_route(
    app: FastAPI,
    *,
    assistant: AssistantService,
    sessions: SessionStore,
    knowledge_base: KnowledgeBase,
    available: bool,
    app_id: str,
    api_key: str,
    api_secret: str,
    asr_host: str,
    stream_factory: Callable[..., Any] = XfyunStream,
    normalize_final: Callable[..., NormalizedTranscript],
    max_session_id_chars: int = 128,
) -> None:
    """Register the browser voice route on top of the typed transport boundary."""

    @app.websocket("/api/voice")
    async def browser_voice(websocket: WebSocket) -> None:
        if not available:
            await websocket.close(code=1013, reason="voice_unavailable")
            return

        if not websocket_origin_allowed(
            websocket.headers.get("origin"),
            websocket.headers.get("host", ""),
            websocket_scheme=websocket.url.scheme,
            forwarded_proto=websocket.headers.get("x-forwarded-proto", ""),
        ):
            await websocket.close(code=1008, reason="voice_origin_forbidden")
            return

        await websocket.accept()
        channel = VoiceWebSocketChannel(websocket)
        runtime = VoiceSessionRuntime(
            emit=channel.emit,
            connection_id=channel.connection_id,
            assistant=assistant,
            sessions=sessions,
            knowledge_base=knowledge_base,
            app_id=app_id,
            api_key=api_key,
            api_secret=api_secret,
            asr_host=asr_host,
            stream_factory=stream_factory,
            normalize_final=normalize_final,
            max_session_id_chars=max_session_id_chars,
        )
        await run_voice_transport(websocket, channel, runtime)


__all__ = [
    "MAX_VOICE_FRAME_BYTES",
    "VoiceWebSocketChannel",
    "dispatch_voice_command",
    "register_voice_route",
    "run_voice_transport",
    "websocket_origin_allowed",
]

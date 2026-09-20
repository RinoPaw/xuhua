"""WebSocket transport for typed realtime voice commands and server events."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .assistant import AssistantService
from .asr_normalization import NormalizedTranscript
from .dataset import KnowledgeBase
from .sessions import SessionStore
from .voice import XfyunStream
from .voice_events import ReadyEvent, VoiceServerEvent, encode_voice_event
from .voice_protocol import VoiceCommand, decode_voice_command
from .voice_session import VoiceSessionRuntime


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
    await runtime.handle_command(command)


async def run_voice_transport(
    websocket: WebSocket,
    channel: VoiceWebSocketChannel,
    runtime: VoiceSessionRuntime,
) -> None:
    """Receive frames, decode commands, and delegate all state to the runtime."""

    try:
        await channel.emit(ReadyEvent())
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data is not None:
                await runtime.handle_audio(data)
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
        if not (app_id.strip() and api_key.strip() and api_secret.strip()):
            await websocket.close(code=1013, reason="voice_unavailable")
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
    "VoiceWebSocketChannel",
    "dispatch_voice_command",
    "register_voice_route",
    "run_voice_transport",
]

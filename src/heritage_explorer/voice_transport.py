"""WebSocket transport for typed realtime voice commands."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .assistant import AssistantService
from .asr_normalization import NormalizedTranscript
from .dataset import KnowledgeBase
from .sessions import SessionStore
from .voice import XfyunStream
from .voice_protocol import VoiceCommand, decode_voice_command
from .voice_session import VoiceSessionRuntime


async def dispatch_voice_command(runtime: VoiceSessionRuntime, command: VoiceCommand) -> None:
    await runtime.handle_command(command)


async def run_voice_transport(runtime: VoiceSessionRuntime) -> None:
    """Receive frames, decode commands, and delegate all state to the runtime."""

    try:
        await runtime.send({"type": "ready"})
        while True:
            message = await runtime.websocket.receive()
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
        runtime = VoiceSessionRuntime(
            websocket,
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
        await run_voice_transport(runtime)


__all__ = [
    "dispatch_voice_command",
    "register_voice_route",
    "run_voice_transport",
]

"""Integration tests for per-turn voice admission and ASR operation caps."""

from __future__ import annotations

import asyncio

import pytest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import heritage_explorer.api as api_module
from heritage_explorer.admission import AdmissionController, AdmissionPolicy
from heritage_explorer.api import create_app
from heritage_explorer.assistant import SearchService
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent
from heritage_explorer.sessions import SessionStore
from heritage_explorer.voice_lifecycle import MAX_ASR_OPERATIONS_PER_CONNECTION


class ControlledAssistant:
    def __init__(self) -> None:
        self.search = SearchService(KnowledgeBase({"items": [], "categories": []}))
        self.sessions = SessionStore()
        self.block = False
        self.calls = 0

    async def stream_turn(self, question: str, *, session_id=None, turn_id=None, **_kwargs):
        self.calls += 1
        if self.block:
            await asyncio.Future()
        yield AssistantEvent(
            "turn.completed",
            session_id or "voice-session",
            turn_id or "turn-id",
            0,
            payload={"answer": f"答复：{question}", "locale": "zh-CN"},
        )


class StalledAsrStream:
    instances: list["StalledAsrStream"] = []

    def __init__(self, **_kwargs) -> None:
        self.candidates = ()
        self.detected_language = "zh"
        self.closed = False
        self.instances.append(self)

    async def start(self) -> None:
        pass

    async def send_audio(self, _data: bytes) -> None:
        pass

    async def finish(self) -> str:
        await asyncio.Future()
        return ""

    async def close(self) -> None:
        self.closed = True


def configure_voice(monkeypatch, stream_factory=None) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")
    if stream_factory is not None:
        monkeypatch.setattr(api_module, "XfyunStream", stream_factory)


def admission(
    chat: AdmissionPolicy,
    asr: AdmissionPolicy | None = None,
) -> AdmissionController:
    return AdmissionController({
        "chat": chat,
        "voice": AdmissionPolicy(4, 20, 20),
        "asr": asr or AdmissionPolicy(8, 120, 40),
    })


def receive_until(ws, predicate, limit=30):
    messages = []
    for _ in range(limit):
        message = ws.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"expected voice event not received: {messages!r}")


def test_voice_turn_occupies_the_same_chat_budget_as_http(monkeypatch) -> None:
    configure_voice(monkeypatch)
    assistant = ControlledAssistant()
    assistant.block = True
    app = create_app(
        assistant=assistant,  # type: ignore[arg-type]
        admission=admission(AdmissionPolicy(1, 20, 20)),
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "text", "text": "语音发问"})
            receive_until(ws, lambda event: event.get("status") == "thinking")
            result = client.post("/api/chat", json={"question": "文字发问"})
            assert result.status_code == 503
            assert result.json()["detail"] == "chat_capacity"

        # Disconnect must release the voice turn even when the provider stalls.
        assistant.block = False
        result = client.post("/api/chat", json={"question": "断开之后"})
        assert result.status_code == 200


def test_one_voice_socket_is_rate_limited_per_assistant_turn(monkeypatch) -> None:
    configure_voice(monkeypatch)
    assistant = ControlledAssistant()
    app = create_app(
        assistant=assistant,  # type: ignore[arg-type]
        admission=admission(AdmissionPolicy(2, 1, 1)),
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as ws:
            ws.receive_json()
            ws.send_json({"type": "text", "text": "第一问"})
            receive_until(ws, lambda event: event.get("type") == "assistant.done")
            ws.send_json({"type": "text", "text": "第二问"})
            messages = receive_until(ws, lambda event: event.get("type") == "error")
            assert messages[-1]["code"].startswith("chat_")

    assert assistant.calls == 1


def test_voice_socket_rejects_unbounded_pending_asr_finalizers(monkeypatch) -> None:
    configure_voice(monkeypatch, StalledAsrStream)
    StalledAsrStream.instances = []
    app = create_app(assistant=ControlledAssistant())  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as ws:
            ws.receive_json()
            for number in range(1, MAX_ASR_OPERATIONS_PER_CONNECTION + 1):
                ws.send_json({"type": "utterance.start"})
                receive_until(
                    ws,
                    lambda e: e.get("status") == "user_speaking"
                    and e.get("utterance_id") == number,
                )
                ws.send_json({"type": "utterance.end"})
                receive_until(
                    ws,
                    lambda e: e.get("status") == "transcribing"
                    and e.get("utterance_id") == number,
                )
            ws.send_json({"type": "utterance.start"})
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1013

    assert len(StalledAsrStream.instances) == MAX_ASR_OPERATIONS_PER_CONNECTION
    assert all(stream.closed for stream in StalledAsrStream.instances)



def test_asr_global_capacity_spans_multiple_voice_connections(monkeypatch) -> None:
    configure_voice(monkeypatch, StalledAsrStream)
    StalledAsrStream.instances = []
    app = create_app(
        assistant=ControlledAssistant(),  # type: ignore[arg-type]
        admission=admission(
            AdmissionPolicy(2, 20, 20),
            AdmissionPolicy(1, 20, 20),
        ),
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as first:
            first.receive_json()
            first.send_json({"type": "utterance.start"})
            receive_until(first, lambda event: event.get("status") == "user_speaking")

            with client.websocket_connect("/api/voice") as second:
                second.receive_json()
                second.send_json({"type": "utterance.start"})
                with pytest.raises(WebSocketDisconnect) as denied:
                    second.receive_json()
                assert denied.value.code == 1013
                assert denied.value.reason == "voice_asr_capacity"

        # Closing the first connection releases the resource for a new socket.
        with client.websocket_connect("/api/voice") as third:
            third.receive_json()
            third.send_json({"type": "utterance.start"})
            receive_until(third, lambda event: event.get("status") == "user_speaking")

    assert len(StalledAsrStream.instances) == 2
    assert all(stream.closed for stream in StalledAsrStream.instances)


def test_asr_rate_budget_applies_across_connections(monkeypatch) -> None:
    configure_voice(monkeypatch, StalledAsrStream)
    StalledAsrStream.instances = []
    app = create_app(
        assistant=ControlledAssistant(),  # type: ignore[arg-type]
        admission=admission(
            AdmissionPolicy(2, 20, 20),
            AdmissionPolicy(2, 2, 1),
        ),
    )
    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as first:
            first.receive_json()
            first.send_json({"type": "utterance.start"})
            receive_until(first, lambda event: event.get("status") == "user_speaking")

        with client.websocket_connect("/api/voice") as second:
            second.receive_json()
            second.send_json({"type": "utterance.start"})
            with pytest.raises(WebSocketDisconnect) as denied:
                second.receive_json()
            assert denied.value.code == 1013
            assert denied.value.reason == "voice_asr_client_rate"

    assert len(StalledAsrStream.instances) == 1

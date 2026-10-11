from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

import heritage_explorer.api as api_module
from heritage_explorer.api import create_app
from heritage_explorer.assistant import SearchService
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent
from heritage_explorer.sessions import SessionStore


def make_kb() -> KnowledgeBase:
    return KnowledgeBase(
        {
            "schema_version": 1,
            "generated_at": "2026-09-20T00:00:00Z",
            "source": {"name": "voice-cancel-test"},
            "categories": [],
            "items": [],
        }
    )


class CancelledAssistant:
    def __init__(self) -> None:
        self.search = SearchService(make_kb())
        self.sessions = SessionStore()

    async def stream_turn(
        self,
        question: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        category: str = "",
        locale_hint: str = "",
    ) -> AsyncIterator[AssistantEvent]:
        assert turn_id is not None
        session = session_id or "voice-session"
        yield AssistantEvent(
            "turn.cancelled",
            session,
            turn_id,
            0,
            payload={"reason": "superseded"},
        )


def receive_until(websocket, predicate, *, limit: int = 12) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for _ in range(limit):
        message = websocket.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"did not receive expected websocket message: {messages!r}")


def test_cancelled_voice_turn_is_forwarded_to_browser(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")

    app = create_app(assistant=CancelledAssistant())  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "text", "text": "介绍汴绣"})
            messages = receive_until(
                websocket,
                lambda message: message.get("type") == "assistant.cancelled",
            )

    assert any(
        message.get("type") == "status" and message.get("status") == "thinking"
        for message in messages
    )
    cancelled = messages[-1]
    assert cancelled["session_id"] == "voice-session"
    assert cancelled["reason"] == "superseded"
    assert cancelled["turn_id"]



def test_text_turn_echoes_client_identity_on_thinking_and_terminal_events(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")

    app = create_app(assistant=CancelledAssistant())  # type: ignore[arg-type]
    requested = "a" * 32
    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            websocket.receive_json()
            websocket.send_json({
                "type": "text",
                "text": "新的问题",
                "turn_id": requested,
            })
            messages = receive_until(
                websocket, lambda event: event.get("type") == "assistant.cancelled"
            )

    assert any(
        event.get("type") == "status"
        and event.get("status") == "thinking"
        and event.get("turn_id") == requested
        for event in messages
    )
    assert messages[-1]["turn_id"] == requested



def test_barge_in_confirms_server_cancellation_before_ack(monkeypatch) -> None:
    import asyncio
    import threading

    class BlockingAssistant(CancelledAssistant):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled = threading.Event()

        async def stream_turn(
            self, question, *, session_id=None, turn_id=None, **_kwargs
        ):
            yield AssistantEvent(
                "response.text.delta", session_id or "voice-session", turn_id, 0,
                payload={"delta": "旧回答", "locale": "zh-CN"},
            )
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled.set()

    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")
    assistant = BlockingAssistant()
    app = create_app(assistant=assistant)  # type: ignore[arg-type]
    request_id = "ab" * 16
    turn_id = "c" * 32

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "text", "text": "第一问", "turn_id": turn_id})
            receive_until(websocket, lambda m: m.get("type") == "assistant.delta")
            websocket.send_json({"type": "barge_in", "request_id": request_id})
            ack = receive_until(
                websocket, lambda m: m.get("type") == "interrupt.ack"
            )[-1]
            assert ack["request_id"] == request_id
            assert ack["reason"] == "barge_in"
            assert ack["turn_id"] == turn_id
            assert ack["cancelled"] is True
            assert assistant.cancelled.is_set()
            status = websocket.receive_json()
            assert status["status"] == "user_speaking"

            websocket.send_json({"type": "interrupt", "request_id": "de" * 16})
            idle_ack = receive_until(
                websocket, lambda m: m.get("type") == "interrupt.ack"
            )[-1]
            assert idle_ack["reason"] == "client_interrupt"
            assert idle_ack["request_id"] == "de" * 16
            assert idle_ack["turn_id"] == ""
            assert idle_ack["cancelled"] is False

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

    search = SearchService(make_kb())
    app = create_app(
        assistant=CancelledAssistant(),  # type: ignore[arg-type]
        search=search,
        sessions=SessionStore(),
    )

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

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

import heritage_explorer.api as api_module
from heritage_explorer.api import create_app
from heritage_explorer.assistant import SearchService
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent
from heritage_explorer.sessions import SessionStore
from heritage_explorer.voice import VoiceProviderError


def make_kb() -> KnowledgeBase:
    return KnowledgeBase(
        {
            "schema_version": 1,
            "generated_at": "2026-09-20T00:00:00Z",
            "source": {"name": "voice-batch-test"},
            "categories": [],
            "items": [],
        }
    )


class RecordingAssistant:
    def __init__(self, search: SearchService) -> None:
        self.search = search
        self.calls: list[str] = []

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
        self.calls.append(question)
        session = session_id or "voice-session"
        yield AssistantEvent(
            "response.text.delta",
            session,
            turn_id,
            0,
            payload={"delta": "好的", "locale": locale_hint or "zh-CN"},
        )
        yield AssistantEvent(
            "turn.completed",
            session,
            turn_id,
            1,
            payload={"answer": "好的", "locale": locale_hint or "zh-CN"},
        )


class MixedBatchStream:
    instances: list["MixedBatchStream"] = []
    first_finish_gate = threading.Event()

    def __init__(self, **kwargs: object) -> None:
        self.index = len(self.__class__.instances)
        self.candidates: tuple[str, ...] = ()
        self.detected_language = "zh"
        self.__class__.instances.append(self)

    async def start(self) -> None:
        return

    async def send_audio(self, _data: bytes) -> None:
        return

    async def finish(self) -> str:
        if self.index == 0:
            await asyncio.to_thread(self.__class__.first_finish_gate.wait, 2)
            raise VoiceProviderError("voice_provider_failed")
        return "新句"

    async def close(self) -> None:
        return


def receive_until(websocket, predicate, *, limit: int = 30) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for _ in range(limit):
        message = websocket.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"did not receive expected websocket message: {messages!r}")


def test_partial_asr_failure_does_not_poison_successful_batch(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")
    monkeypatch.setattr(api_module, "XfyunStream", MixedBatchStream)
    MixedBatchStream.instances.clear()
    MixedBatchStream.first_finish_gate.clear()

    search = SearchService(make_kb())
    assistant = RecordingAssistant(search)
    app = create_app(
        assistant=assistant,  # type: ignore[arg-type]
        search=search,
        sessions=SessionStore(),
    )

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            receive_until(websocket, lambda message: message.get("status") == "transcribing")

            websocket.send_json({"type": "utterance.start"})
            receive_until(
                websocket,
                lambda message: message.get("status") == "user_speaking"
                and message.get("utterance_id") == 2,
            )
            websocket.send_json({"type": "utterance.end"})
            MixedBatchStream.first_finish_gate.set()

            messages = receive_until(
                websocket,
                lambda message: message.get("type") == "assistant.done",
            )

    assert not any(message.get("type") == "error" for message in messages)
    transcript = next(message for message in messages if message.get("type") == "user.transcript")
    assert transcript["text"] == "新句"
    assert assistant.calls == ["新句"]

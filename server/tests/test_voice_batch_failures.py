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
        self.sessions = SessionStore()
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


class CloseFailBatchStream:
    instances: list["CloseFailBatchStream"] = []

    def __init__(self, **kwargs: object) -> None:
        self.candidates: tuple[str, ...] = ()
        self.detected_language = "zh"
        self.__class__.instances.append(self)

    async def start(self) -> None:
        return

    async def send_audio(self, _data: bytes) -> None:
        return

    async def finish(self) -> str:
        return "可用句"

    async def close(self) -> None:
        raise RuntimeError("cleanup failed")


class NameCallStream:
    instances: list["NameCallStream"] = []

    def __init__(self, **kwargs: object) -> None:
        self.hotwords = tuple(kwargs.get("hotwords", ()))
        self.candidates = ("叙华",)
        self.detected_language = "zh"
        self.__class__.instances.append(self)

    async def start(self) -> None:
        return

    async def send_audio(self, _data: bytes) -> None:
        return

    async def finish(self) -> str:
        return "叙华"

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


def configure_voice(monkeypatch, stream_factory) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")
    monkeypatch.setattr(api_module, "XfyunStream", stream_factory)


def test_partial_asr_failure_does_not_poison_successful_batch(monkeypatch) -> None:
    configure_voice(monkeypatch, MixedBatchStream)
    MixedBatchStream.instances.clear()
    MixedBatchStream.first_finish_gate.clear()

    assistant = RecordingAssistant(SearchService(make_kb()))
    app = create_app(assistant=assistant)  # type: ignore[arg-type]

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


def test_asr_close_failure_does_not_poison_successful_batch(monkeypatch) -> None:
    configure_voice(monkeypatch, CloseFailBatchStream)
    CloseFailBatchStream.instances.clear()

    assistant = RecordingAssistant(SearchService(make_kb()))
    app = create_app(assistant=assistant)  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(
                websocket,
                lambda message: message.get("type") == "assistant.done",
            )

    assert not any(message.get("type") == "error" for message in messages)
    transcript = next(message for message in messages if message.get("type") == "user.transcript")
    assert transcript["text"] == "可用句"
    assert assistant.calls == ["可用句"]


def test_assistant_name_is_hotword_and_uses_local_acknowledgement(monkeypatch) -> None:
    configure_voice(monkeypatch, NameCallStream)
    NameCallStream.instances.clear()

    assistant = RecordingAssistant(SearchService(make_kb()))
    app = create_app(assistant=assistant)  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(
                websocket,
                lambda message: message.get("type") == "assistant.done",
            )

    transcript = next(message for message in messages if message.get("type") == "user.transcript")
    done = next(message for message in messages if message.get("type") == "assistant.done")
    assert transcript["text"] == "叙华"
    assert done["text"] == "我在。"
    assert assistant.calls == []
    assert NameCallStream.instances[0].hotwords[0] == "叙华"

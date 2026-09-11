from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx

import heritage_explorer.api as api_module
from heritage_explorer.api import create_app
from heritage_explorer.asr_normalization import NormalizedSpan
from heritage_explorer.dataset import KnowledgeBase, item_to_dict
from heritage_explorer.models import AssistantEvent, SearchResponse
from heritage_explorer.sessions import SessionStore


def make_kb() -> KnowledgeBase:
    return KnowledgeBase(
        {
            "schema_version": 7,
            "generated_at": "2026-08-20T00:00:00Z",
            "source": {"name": "offline-fixture"},
            "categories": [{"id": 1, "name": "传统技艺", "item_count": 2}],
            "items": [
                {
                    "id": "item-1",
                    "title": "木雕技艺",
                    "family": "雕刻",
                    "category": "传统技艺",
                    "summary": "浙江木雕工艺",
                    "content": "木雕历史悠久。",
                    "search_text": "木雕技艺 浙江",
                    "level": "国家级",
                    "province": "浙江省",
                    "city": "东阳市",
                    "district": "吴宁街道",
                    "display_forms": ["木雕"],
                    "suitable_scenarios": ["展览"],
                },
                {
                    "id": "item-2",
                    "title": "龙舞",
                    "family": "舞蹈",
                    "category": "传统舞蹈",
                    "summary": "广东民间舞蹈",
                    "content": "节庆表演。",
                    "search_text": "龙舞 广东",
                    "level": "省级",
                    "province": "广东省",
                    "city": "东莞市",
                    "district": "莞城区",
                },
            ],
        }
    )


class RecordingSearch:
    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.knowledge_base = knowledge_base
        self.calls: list[dict[str, object]] = []

    def search(self, query: str = "", **kwargs: object) -> SearchResponse:
        self.calls.append({"query": query, **kwargs})
        limit = int(kwargs.get("limit", 30))
        offset = int(kwargs.get("offset", 0))
        items = tuple(self.knowledge_base.items[offset : offset + limit])
        return SearchResponse(items=items, total=len(self.knowledge_base.items))


class RecordingAssistant:
    def __init__(self, search: RecordingSearch, events: tuple[AssistantEvent, ...] = ()) -> None:
        self.search = search
        self.events = events
        self.calls: list[dict[str, str | None]] = []

    async def stream_turn(
        self,
        question: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        category: str = "",
        locale_hint: str = "",
    ) -> AsyncIterator[AssistantEvent]:
        self.calls.append(
            {
                "question": question,
                "session_id": session_id,
                "turn_id": turn_id,
                "category": category,
                "locale_hint": locale_hint,
            }
        )
        for event in self.events:
            yield event


class ASGIClient:
    def __init__(self, app: object) -> None:
        self.app = app

    def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)  # type: ignore[arg-type]
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: object) -> httpx.Response:
        return self.request("POST", url, **kwargs)


class FakeXfyunStream:
    instances: list["FakeXfyunStream"] = []
    transcript = ""
    candidate_texts: tuple[str, ...] = ()
    partial = ""
    provider_language = "zh"
    block_finish = False
    finish_gate = threading.Event()

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.on_partial = kwargs.get("on_partial")
        self.finish_called = threading.Event()
        self.closed = threading.Event()
        self.block_finish = self.__class__.block_finish
        self.transcript = self.__class__.transcript
        self.candidates = self.__class__.candidate_texts or (
            (self.transcript,) if self.transcript else ()
        )
        self.partial = self.__class__.partial
        self.detected_language = self.__class__.provider_language
        self.__class__.instances.append(self)

    async def start(self) -> None:
        return

    async def send_audio(self, _data: bytes) -> None:
        return

    async def finish(self) -> str:
        self.finish_called.set()
        if self.block_finish:
            await asyncio.to_thread(self.__class__.finish_gate.wait, 2)
        if self.partial and self.on_partial is not None:
            await self.on_partial(self.partial)
        return self.transcript

    async def close(self) -> None:
        self.closed.set()


class VoiceRecordingAssistant:
    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.calls: list[dict[str, str | None]] = []
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.release = threading.Event()

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
        self.calls.append(
            {
                "question": question,
                "session_id": session_id,
                "turn_id": turn_id,
                "category": category,
                "locale_hint": locale_hint,
            }
        )
        self.started.set()
        try:
            yield AssistantEvent(
                "response.text.delta",
                session,
                turn_id,
                0,
                payload={"delta": "好的"},
            )
            while self.block and not self.release.is_set():
                await asyncio.sleep(0.01)
            yield AssistantEvent(
                "turn.completed",
                session,
                turn_id,
                1,
                payload={"answer": "好的"},
            )
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def voice_test_client(monkeypatch, assistant: VoiceRecordingAssistant) -> TestClient:
    monkeypatch.setattr(api_module, "XF_APP_ID", "test-app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "test-key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "test-secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "iat.xf-yun.com")
    FakeXfyunStream.instances.clear()
    FakeXfyunStream.block_finish = False
    FakeXfyunStream.partial = ""
    FakeXfyunStream.candidate_texts = ()
    FakeXfyunStream.provider_language = "zh"
    FakeXfyunStream.finish_gate.set()
    monkeypatch.setattr(api_module, "XfyunStream", FakeXfyunStream)
    search = RecordingSearch(make_kb())
    return TestClient(
        create_app(
            assistant=assistant,  # type: ignore[arg-type]
            search=search,  # type: ignore[arg-type]
            sessions=SessionStore(),
        )
    )


def receive_until(websocket, predicate, *, limit: int = 20) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for _ in range(limit):
        message = websocket.receive_json()
        messages.append(message)
        if predicate(message):
            return messages
    raise AssertionError(f"did not receive expected websocket message: {messages!r}")


def build_client(
    *,
    events: tuple[AssistantEvent, ...] = (),
) -> tuple[ASGIClient, KnowledgeBase, RecordingSearch, RecordingAssistant]:
    kb = make_kb()
    search = RecordingSearch(kb)
    assistant = RecordingAssistant(search, events)
    client = ASGIClient(
        create_app(
            assistant=assistant,  # type: ignore[arg-type]
            search=search,  # type: ignore[arg-type]
            sessions=SessionStore(),
        )
    )
    return client, kb, search, assistant


def parse_sse(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append(
            {
                "event": lines["event"],
                "id": int(lines["id"]),
                "data": json.loads(lines["data"]),
            }
        )
    return events


def test_health_aliases_and_meta_expose_stable_contract() -> None:
    client, _kb, _search, _assistant = build_client()
    for path in ("/healthz", "/api/health"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "0.2.0"}

    response = client.get("/api/meta")
    assert response.status_code == 200
    assert response.json()["item_count"] == 2
    assert response.json()["capabilities"]["realtime_voice"] is False


def test_frontend_static_routes_coexist_with_api_routes(tmp_path, monkeypatch) -> None:
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body>offline ui</body></html>", encoding="utf-8"
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('offline');", encoding="utf-8")
    monkeypatch.setattr(api_module, "FRONTEND_DIR", tmp_path)
    client, _kb, _search, _assistant = build_client()
    assert client.get("/").text == "<!doctype html><html><body>offline ui</body></html>"
    assert client.get("/assets/app.js").text == "console.log('offline');"
    assert client.get("/api/health").json()["status"] == "ok"


def test_items_and_detail_return_public_shapes_and_forward_filters() -> None:
    client, kb, search, _assistant = build_client()
    response = client.get(
        "/api/items",
        params={
            "q": "木雕",
            "category": "传统技艺",
            "province": "浙江省",
            "level": "国家级",
            "district": "吴宁街道",
            "keywords": "展览",
            "limit": 1,
            "offset": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["items"] == [item_to_dict(kb.items[1])]
    assert search.calls[-1]["query"] == "木雕"
    detail = client.get("/api/items/item-1")
    assert detail.status_code == 200
    assert detail.json()["content"] == "木雕历史悠久。"
    assert client.get("/api/items/does-not-exist").status_code == 404


def test_chat_sse_preserves_order_and_payload() -> None:
    events = (
        AssistantEvent("turn.started", "session-1", "turn-1", 0, payload={"question": "介绍"}),
        AssistantEvent(
            "response.sources", "session-1", "turn-1", 1, payload={"sources": [{"id": "item-1"}]}
        ),
        AssistantEvent("turn.completed", "session-1", "turn-1", 2, payload={"answer": "完成"}),
    )
    client, _kb, _search, assistant = build_client(events=events)
    response = client.post(
        "/api/chat",
        json={"question": "  介绍  ", "session_id": " session-1 ", "category": " 传统技艺 "},
    )
    parsed = parse_sse(response.text)
    assert [item["event"] for item in parsed] == [event.type for event in events]
    assert assistant.calls[0]["question"] == "介绍"
    assert assistant.calls[0]["session_id"] == "session-1"


def test_voice_empty_final_is_rejected_without_starting_answer(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant()
    FakeXfyunStream.transcript = ""
    with voice_test_client(monkeypatch, assistant) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "utterance.start"})
            receive_until(
                websocket,
                lambda message: message.get("type") == "status"
                and message.get("status") == "user_speaking",
            )
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(
                websocket,
                lambda message: message.get("type") == "utterance.rejected",
            )
            assert messages[-1]["utterance_id"] == 1
            assert assistant.calls == []


def test_voice_partial_is_calibrated_by_final(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant()
    FakeXfyunStream.transcript = "你好"
    FakeXfyunStream.partial = "你"
    with voice_test_client(monkeypatch, assistant) as client:
        FakeXfyunStream.partial = "你"
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(websocket, lambda message: message.get("type") == "assistant.done")
            partial = next(message for message in messages if message.get("type") == "user.partial")
            final = next(message for message in messages if message.get("type") == "user.transcript")
            assert partial["text"] == "你"
            assert final["text"] == "你好"
            assert final["asr_engine"] == "chinese"


def test_voice_overlapping_finals_merge_in_id_order(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant()
    FakeXfyunStream.transcript = "旧句"
    FakeXfyunStream.block_finish = True
    FakeXfyunStream.finish_gate.clear()
    with voice_test_client(monkeypatch, assistant) as client:
        FakeXfyunStream.block_finish = True
        FakeXfyunStream.finish_gate.clear()
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            receive_until(websocket, lambda message: message.get("status") == "transcribing")
            first = FakeXfyunStream.instances[0]

            FakeXfyunStream.block_finish = False
            FakeXfyunStream.transcript = "新句"
            websocket.send_json({"type": "utterance.start"})
            receive_until(
                websocket,
                lambda message: message.get("status") == "user_speaking"
                and message.get("utterance_id") == 2,
            )
            websocket.send_json({"type": "utterance.end"})
            assert not first.closed.is_set()
            FakeXfyunStream.finish_gate.set()
            messages = receive_until(websocket, lambda message: message.get("type") == "assistant.done")
            final = next(message for message in messages if message.get("type") == "user.transcript")
            assert final["text"] == "旧句 新句"
            assert assistant.calls[0]["question"] == "旧句 新句"


def test_voice_barge_in_cancels_answer_without_closing_asr(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant(block=True)
    with voice_test_client(monkeypatch, assistant) as client:
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "text", "text": "正在回答"})
            assert assistant.started.wait(2)
            receive_until(websocket, lambda message: message.get("status") == "thinking")
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            asr_stream = FakeXfyunStream.instances[-1]
            websocket.send_json({"type": "barge_in"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            assert assistant.cancelled.wait(2)
            assert not asr_stream.closed.is_set()


def test_voice_context_normalizes_final_and_builds_hotwords(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant()
    normalized_calls: list[dict[str, object]] = []

    def fake_normalize(raw_text: str, **kwargs: object) -> object:
        normalized_calls.append({"raw_text": raw_text, **kwargs})
        return SimpleNamespace(
            raw_text=raw_text,
            canonical_text="汴绣",
            spans=(NormalizedSpan(0, 2, "卞绣", "汴绣", 0.9, "test"),),
        )

    monkeypatch.setattr(api_module, "normalize_asr_final", fake_normalize)
    FakeXfyunStream.transcript = "卞绣"
    with voice_test_client(monkeypatch, assistant) as client:
        FakeXfyunStream.candidate_texts = ("卞绣", "汴绣")
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {"type": "context", "category": "传统技艺", "titles": ["苏绣", "木雕技艺"]}
            )
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(websocket, lambda message: message.get("type") == "assistant.done")
            final = next(message for message in messages if message.get("type") == "user.transcript")
            assert final["text"] == "汴绣"
            assert final["raw_text"] == "卞绣"
            assert normalized_calls[0]["asr_candidates"] == ("卞绣", "汴绣")
            assert FakeXfyunStream.instances[0].kwargs["hotwords"] == (
                "传统技艺",
                "苏绣",
                "木雕技艺",
            )


def test_tts_maps_resolved_locales_to_allowlisted_voices(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    class FakeCommunicate:
        def __init__(self, text: str, **kwargs: str) -> None:
            calls.append({"text": text, **kwargs})

        async def stream(self):
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setattr(api_module.edge_tts, "Communicate", FakeCommunicate)
    client, _kb, _search, _assistant = build_client()
    english = client.get(
        "/api/tts", params={"text": "Kunqu (昆曲) is a living tradition.", "locale": "en-US"}
    )
    cantonese = client.get(
        "/api/tts", params={"text": "昆曲係一项传统艺术。", "locale": "yue-HK"}
    )
    assert english.status_code == 200
    assert cantonese.status_code == 200
    assert [call["voice"] for call in calls] == [
        "en-US-JennyNeural",
        "zh-HK-HiuMaanNeural",
    ]


def test_single_asr_stream_preserves_detected_english_locale(monkeypatch) -> None:
    assistant = VoiceRecordingAssistant()
    FakeXfyunStream.transcript = "Tell me about paper cutting"

    def fail_chinese_normalizer(*args: object, **kwargs: object) -> object:
        raise AssertionError("non-Chinese speech must bypass Mandarin pinyin normalization")

    monkeypatch.setattr(api_module, "normalize_asr_final", fail_chinese_normalizer)
    with voice_test_client(monkeypatch, assistant) as client:
        FakeXfyunStream.provider_language = "en"
        with client.websocket_connect("/api/voice") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "context", "locale_hint": "en-US"})
            websocket.send_json({"type": "utterance.start"})
            receive_until(websocket, lambda message: message.get("status") == "user_speaking")
            websocket.send_json({"type": "utterance.end"})
            messages = receive_until(websocket, lambda message: message.get("type") == "assistant.done")

    transcript = next(message for message in messages if message.get("type") == "user.transcript")
    assert transcript["locale"] == "en-US"
    assert transcript["asr_engine"] == "chinese"
    assert assistant.calls[0]["locale_hint"] == "en-US"

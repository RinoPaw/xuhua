from __future__ import annotations

from fastapi.testclient import TestClient

import heritage_explorer.api as api_module
from heritage_explorer.api import create_app
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class _Search:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBase({"items": [], "categories": []})

    def search(self, *_args, **_kwargs) -> SearchResponse:
        return SearchResponse(items=(), total=0)


class _Assistant:
    def __init__(self) -> None:
        self.search = _Search()
        self.sessions = SessionStore()


class _FakeCommunicate:
    calls: list[dict[str, str]] = []

    def __init__(self, text: str, *, voice: str, rate: str, pitch: str) -> None:
        self.__class__.calls.append(
            {"text": text, "voice": voice, "rate": rate, "pitch": pitch}
        )

    async def stream(self):
        yield {"type": "audio", "data": b"first"}
        yield {"type": "audio", "data": b"second"}


def test_tts_text_is_exchanged_for_a_reusable_short_stream_token(monkeypatch) -> None:
    _FakeCommunicate.calls.clear()
    monkeypatch.setattr(api_module.edge_tts, "Communicate", _FakeCommunicate)
    app = create_app(assistant=_Assistant())  # type: ignore[arg-type]

    with TestClient(app) as client:
        prepared = client.post(
            "/api/tts",
            json={
                "text": "汴绣是什么？",
                "locale": "zh-CN",
                "trace_id": "trace-1",
                "segment": 0,
                "reason": "first_sentence",
            },
        )
        assert prepared.status_code == 200
        token = prepared.json()["token"]
        assert len(token) >= 16
        assert "汴绣" not in token

        stream_path = f"/api/tts/{token}"
        assert "text=" not in stream_path
        first = client.get(stream_path)
        assert first.status_code == 200
        assert first.content == b"firstsecond"
        assert first.headers["cache-control"] == "no-store"

        retry = client.get(f"{stream_path}?tts_retry=1")
        assert retry.status_code == 200
        assert retry.content == b"firstsecond"

    assert [call["text"] for call in _FakeCommunicate.calls] == ["汴绣是什么？", "汴绣是什么？"]

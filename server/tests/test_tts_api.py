from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import httpx

import heritage_explorer.api as api_module
from heritage_explorer.admission import AdmissionController, AdmissionPolicy
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


def test_tts_text_is_exchanged_for_a_same_client_reusable_short_stream_token(monkeypatch) -> None:
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
        assert prepared.headers["cache-control"] == "no-store"
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


def test_tts_ticket_cannot_be_replayed_by_another_client(monkeypatch) -> None:
    _FakeCommunicate.calls.clear()
    monkeypatch.setattr(api_module.edge_tts, "Communicate", _FakeCommunicate)
    app = create_app(assistant=_Assistant())  # type: ignore[arg-type]

    async def scenario() -> None:
        owner_transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 51000))
        other_transport = httpx.ASGITransport(app=app, client=("203.0.113.11", 52000))
        async with (
            httpx.AsyncClient(transport=owner_transport, base_url="http://testserver") as owner,
            httpx.AsyncClient(transport=other_transport, base_url="http://testserver") as other,
        ):
            prepared = await owner.post(
                "/api/tts",
                json={"text": "汴绣是什么？", "locale": "zh-CN"},
            )
            assert prepared.status_code == 200
            token = prepared.json()["token"]

            stolen = await other.get(f"/api/tts/{token}")
            assert stolen.status_code == 404
            assert stolen.json()["detail"] == "tts_ticket_not_found"

            valid = await owner.get(f"/api/tts/{token}")
            assert valid.status_code == 200
            assert valid.content == b"firstsecond"

    asyncio.run(scenario())
    assert [call["text"] for call in _FakeCommunicate.calls] == ["汴绣是什么？"]


def test_invalid_tts_token_does_not_spend_synthesis_rate_budget(monkeypatch) -> None:
    _FakeCommunicate.calls.clear()
    monkeypatch.setattr(api_module.edge_tts, "Communicate", _FakeCommunicate)
    admission = AdmissionController(
        {
            "tts_ticket": AdmissionPolicy(1, 10, 10),
            "tts": AdmissionPolicy(1, 1, 1),
        }
    )
    app = create_app(assistant=_Assistant(), admission=admission)  # type: ignore[arg-type]

    with TestClient(app) as client:
        prepared = client.post(
            "/api/tts",
            json={"text": "汴绣", "locale": "zh-CN"},
        )
        assert prepared.status_code == 200
        token = prepared.json()["token"]

        missing = client.get(f"/api/tts/{'x' * 32}")
        assert missing.status_code == 404

        valid = client.get(f"/api/tts/{token}")
        assert valid.status_code == 200
        assert valid.content == b"firstsecond"

        replay = client.get(f"/api/tts/{token}?tts_retry=1")
        assert replay.status_code == 429
        assert replay.json()["detail"] == "tts_global_rate"
        assert replay.headers["retry-after"] == "60"

    assert [call["text"] for call in _FakeCommunicate.calls] == ["汴绣"]


def test_tts_holds_synthesis_capacity_for_the_full_stream(monkeypatch) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingCommunicate:
        def __init__(self, _text: str, **_kwargs: str) -> None:
            pass

        async def stream(self):
            started.set()
            yield {"type": "audio", "data": b"first"}
            await release.wait()
            yield {"type": "audio", "data": b"second"}

    monkeypatch.setattr(api_module.edge_tts, "Communicate", BlockingCommunicate)
    admission = AdmissionController(
        {
            "tts_ticket": AdmissionPolicy(1, 10, 10),
            "tts": AdmissionPolicy(1, 10, 10),
        }
    )
    app = create_app(assistant=_Assistant(), admission=admission)  # type: ignore[arg-type]

    async def scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first_ticket = await client.post("/api/tts", json={"text": "第一段"})
            second_ticket = await client.post("/api/tts", json={"text": "第二段"})
            first_path = f"/api/tts/{first_ticket.json()['token']}"
            second_path = f"/api/tts/{second_ticket.json()['token']}"

            first = asyncio.create_task(client.get(first_path))
            await asyncio.wait_for(started.wait(), timeout=1)

            second = await client.get(second_path)
            assert second.status_code == 503
            assert second.json()["detail"] == "tts_capacity"

            release.set()
            first_response = await asyncio.wait_for(first, timeout=1)
            assert first_response.status_code == 200
            assert first_response.content == b"firstsecond"

            third = await client.get(second_path)
            assert third.status_code == 200

    asyncio.run(scenario())

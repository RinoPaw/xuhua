from __future__ import annotations

import asyncio

import httpx
import pytest

from heritage_explorer.admission import (
    AdmissionController,
    AdmissionDenied,
    AdmissionMiddleware,
    AdmissionPolicy,
    client_key_from_scope,
)
from heritage_explorer.api import create_app
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent, SearchResponse
from heritage_explorer.sessions import SessionStore


def test_admission_capacity_is_held_by_lease_and_released_once() -> None:
    async def scenario() -> None:
        controller = AdmissionController(
            {"chat": AdmissionPolicy(1, 10, 10)}
        )
        first = await controller.acquire("chat", "client-a")
        with pytest.raises(AdmissionDenied) as denied:
            await controller.acquire("chat", "client-b")
        assert denied.value.reason == "capacity"

        await first.release()
        await first.release()
        second = await controller.acquire("chat", "client-b")
        await second.release()

    asyncio.run(scenario())


def test_cancelled_release_still_returns_the_capacity_slot() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"chat": AdmissionPolicy(1, 10, 10)})
        lease = await controller.acquire("chat", "client-a")

        await controller._lock.acquire()
        release_task = asyncio.create_task(lease.release())
        await asyncio.sleep(0)
        release_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await release_task
        controller._lock.release()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        replacement = await controller.acquire("chat", "client-b")
        await replacement.release()

    asyncio.run(scenario())


def test_tts_ticket_and_synthesis_use_independent_rate_budgets() -> None:
    async def scenario() -> None:
        controller = AdmissionController(
            {
                "tts_ticket": AdmissionPolicy(1, 1, 1),
                "tts": AdmissionPolicy(1, 1, 1),
            }
        )
        await controller.charge("tts_ticket", "client-a")

        stream = await controller.acquire("tts", "client-a")
        with pytest.raises(AdmissionDenied) as capacity_denied:
            await controller.acquire("tts", "client-b")
        assert capacity_denied.value.reason == "capacity"
        await stream.release()

        with pytest.raises(AdmissionDenied) as synthesis_denied:
            await controller.acquire("tts", "client-b")
        assert synthesis_denied.value.reason == "global_rate"

        with pytest.raises(AdmissionDenied) as ticket_denied:
            await controller.charge("tts_ticket", "client-a")
        assert ticket_denied.value.reason == "global_rate"

    asyncio.run(scenario())


def test_admission_applies_client_and_global_rolling_windows() -> None:
    now = [100.0]

    async def scenario() -> None:
        controller = AdmissionController(
            {"chat": AdmissionPolicy(5, 3, 2)},
            clock=lambda: now[0],
        )
        for _ in range(2):
            lease = await controller.acquire("chat", "client-a")
            await lease.release()

        with pytest.raises(AdmissionDenied) as client_denied:
            await controller.acquire("chat", "client-a")
        assert client_denied.value.reason == "client_rate"
        assert client_denied.value.retry_after == 60

        lease = await controller.acquire("chat", "client-b")
        await lease.release()
        with pytest.raises(AdmissionDenied) as global_denied:
            await controller.acquire("chat", "client-c")
        assert global_denied.value.reason == "global_rate"

        now[0] += 61.0
        lease = await controller.acquire("chat", "client-c")
        await lease.release()

    asyncio.run(scenario())


def test_client_key_uses_resolved_asgi_peer(monkeypatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    assert client_key_from_scope({"client": ("203.0.113.7", 4321)}) == "203.0.113.7"
    assert client_key_from_scope({}) == "unknown"


def test_render_client_key_uses_cloudflare_connecting_ip(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    scope = {
        "client": ("10.0.0.12", 443),
        "headers": [(b"cf-connecting-ip", b"203.0.113.17")],
    }
    assert client_key_from_scope(scope) == "203.0.113.17"


def test_render_client_key_rejects_ambiguous_or_invalid_cloudflare_headers(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    proxy = ("10.0.0.12", 443)
    assert client_key_from_scope(
        {
            "client": proxy,
            "headers": [
                (b"cf-connecting-ip", b"203.0.113.17"),
                (b"cf-connecting-ip", b"198.51.100.9"),
            ],
        }
    ) == "10.0.0.12"
    assert client_key_from_scope(
        {
            "client": proxy,
            "headers": [(b"cf-connecting-ip", b"not-an-ip")],
        }
    ) == "10.0.0.12"


def test_non_render_client_key_ignores_raw_forwarding_headers(monkeypatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    scope = {
        "client": ("127.0.0.1", 50000),
        "headers": [
            (b"cf-connecting-ip", b"203.0.113.17"),
            (b"x-forwarded-for", b"198.51.100.9"),
        ],
    }
    assert client_key_from_scope(scope) == "127.0.0.1"


def test_middleware_owns_ticket_issuance_but_not_validated_tts_streams() -> None:
    assert AdmissionMiddleware.service_for_scope(
        {"type": "http", "method": "POST", "path": "/api/tts"}
    ) == "tts_ticket"
    assert AdmissionMiddleware.service_for_scope(
        {"type": "http", "method": "GET", "path": "/api/tts/private-token"}
    ) is None
    assert AdmissionMiddleware.service_for_scope(
        {"type": "http", "method": "GET", "path": "/api/tts"}
    ) is None


class _Search:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBase({"items": [], "categories": []})

    def search(self, *_args, **_kwargs) -> SearchResponse:
        return SearchResponse(items=(), total=0)


class _BlockingAssistant:
    def __init__(self, search: _Search, started: asyncio.Event, release: asyncio.Event) -> None:
        self.search = search
        self.sessions = SessionStore()
        self.started = started
        self.release = release

    async def stream_turn(self, _question: str, **_kwargs):
        self.started.set()
        await self.release.wait()
        yield AssistantEvent(
            "turn.completed",
            "session-1",
            "turn-1",
            0,
            payload={"answer": "完成"},
        )


async def _chat_capacity_scenario() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    search = _Search()
    assistant = _BlockingAssistant(search, started, release)
    admission = AdmissionController(
        {"chat": AdmissionPolicy(1, 20, 20)}
    )
    app = create_app(
        assistant=assistant,  # type: ignore[arg-type]
        admission=admission,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = asyncio.create_task(client.post("/api/chat", json={"question": "第一问"}))
        await asyncio.wait_for(started.wait(), timeout=1)

        second = await client.post("/api/chat", json={"question": "第二问"})
        assert second.status_code == 503
        assert second.json()["detail"] == "chat_capacity"
        assert second.headers["retry-after"] == "1"

        release.set()
        response = await asyncio.wait_for(first, timeout=1)
        assert response.status_code == 200


def test_chat_holds_admission_for_the_full_sse_stream() -> None:
    asyncio.run(_chat_capacity_scenario())

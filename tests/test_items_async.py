from __future__ import annotations

import asyncio
import threading

import httpx

import heritage_explorer.api as api_module
from heritage_explorer.api import create_app
from heritage_explorer.dataset import KnowledgeBase, item_to_dict as real_item_to_dict
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class SearchProbe:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBase(
            {
                "schema_version": 7,
                "generated_at": "2026-09-20T00:00:00Z",
                "source": {"name": "test"},
                "categories": [],
                "items": [
                    {
                        "id": "item-1",
                        "title": "木雕技艺",
                        "family": "雕刻",
                        "category": "传统技艺",
                        "summary": "浙江木雕工艺",
                        "content": "木雕历史悠久。",
                        "search_text": "木雕技艺 浙江",
                    }
                ],
            }
        )
        self.thread_ids: list[int] = []

    def search(self, _query: str = "", **_kwargs: object) -> SearchResponse:
        self.thread_ids.append(threading.get_ident())
        return SearchResponse(items=(), total=0)


class DummyAssistant:
    def __init__(self, search: SearchProbe) -> None:
        self.search = search
        self.sessions = SessionStore()

    async def aclose(self) -> None:
        return

    async def stream_turn(self, *_args: object, **_kwargs: object):
        if False:
            yield None


def make_app(search: SearchProbe):
    return create_app(assistant=DummyAssistant(search))  # type: ignore[arg-type]


def test_items_search_runs_outside_the_asgi_event_loop_thread() -> None:
    search = SearchProbe()
    app = make_app(search)

    async def scenario() -> tuple[int, httpx.Response]:
        event_loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/items", params={"q": "木雕"})
        return event_loop_thread, response

    event_loop_thread, response = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.json() == {"total": 0, "limit": 30, "offset": 0, "items": []}
    assert search.thread_ids
    assert search.thread_ids[0] != event_loop_thread


def test_item_detail_enrichment_runs_outside_the_asgi_event_loop_thread(monkeypatch) -> None:
    search = SearchProbe()
    detail_threads: list[int] = []

    def record_item_to_dict(item, **kwargs):
        detail_threads.append(threading.get_ident())
        return real_item_to_dict(item, **kwargs)

    monkeypatch.setattr(api_module, "item_to_dict", record_item_to_dict)
    app = make_app(search)

    async def scenario() -> tuple[int, httpx.Response]:
        event_loop_thread = threading.get_ident()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/items/item-1")
        return event_loop_thread, response

    event_loop_thread, response = asyncio.run(scenario())
    assert response.status_code == 200
    assert response.json()["content"] == "木雕历史悠久。"
    assert detail_threads
    assert detail_threads[0] != event_loop_thread

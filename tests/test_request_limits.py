from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from heritage_explorer.api import create_app
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent, SearchResponse
from heritage_explorer.request_limits import RequestBodyLimitMiddleware
from heritage_explorer.sessions import SessionStore


async def _run_middleware(
    *,
    chunks: list[dict[str, object]],
    max_bytes: int,
    content_length: int | None = None,
) -> tuple[bool, list[dict[str, object]], bytes]:
    called = False
    replayed = b""

    async def inner(scope, receive, send) -> None:
        nonlocal called, replayed
        called = True
        message = await receive()
        replayed = bytes(message.get("body") or b"")
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": headers,
    }
    messages = list(chunks)

    async def receive() -> dict[str, object]:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    sent: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    middleware = RequestBodyLimitMiddleware(inner, max_bytes=max_bytes)
    await middleware(scope, receive, send)
    return called, sent, replayed


def test_content_length_over_limit_is_rejected_before_downstream() -> None:
    called, sent, _body = asyncio.run(
        _run_middleware(
            chunks=[],
            max_bytes=10,
            content_length=11,
        )
    )
    assert called is False
    assert sent[0]["status"] == 413


def test_chunked_body_is_bounded_without_trusting_content_length() -> None:
    called, sent, _body = asyncio.run(
        _run_middleware(
            chunks=[
                {"type": "http.request", "body": b"123456", "more_body": True},
                {"type": "http.request", "body": b"789012", "more_body": False},
            ],
            max_bytes=10,
        )
    )
    assert called is False
    assert sent[0]["status"] == 413


def test_stalled_body_is_rejected_before_downstream() -> None:
    async def scenario() -> tuple[bool, list[dict[str, object]]]:
        called = False
        sent: list[dict[str, object]] = []

        async def inner(_scope, _receive, _send) -> None:
            nonlocal called
            called = True

        async def receive() -> dict[str, object]:
            await asyncio.sleep(1)
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        middleware = RequestBodyLimitMiddleware(inner, max_bytes=10, read_timeout=0.01)
        await middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/chat",
                "headers": [],
            },
            receive,
            send,
        )
        return called, sent

    called, sent = asyncio.run(scenario())
    assert called is False
    assert sent[0]["status"] == 408
    assert sent[1]["body"] == b'{"detail":"request_body_timeout"}'


def test_bounded_body_is_replayed_once_to_downstream() -> None:
    called, sent, body = asyncio.run(
        _run_middleware(
            chunks=[
                {"type": "http.request", "body": b"123", "more_body": True},
                {"type": "http.request", "body": b"456", "more_body": False},
            ],
            max_bytes=10,
        )
    )
    assert called is True
    assert sent[0]["status"] == 204
    assert body == b"123456"


class _Search:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBase({"items": [], "categories": []})

    def search(self, *_args, **_kwargs) -> SearchResponse:
        return SearchResponse(items=(), total=0)


class _Assistant:
    def __init__(self) -> None:
        self.search = _Search()
        self.sessions = SessionStore()

    async def stream_turn(self, *_args, **_kwargs) -> AsyncIterator[AssistantEvent]:
        if False:
            yield AssistantEvent("turn.completed", "", "", 0)


def test_public_chat_rejects_oversized_raw_json_before_pydantic() -> None:
    app = create_app(assistant=_Assistant())  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"question": "合法问题", "ignored": "x" * 70_000},
        )
    assert response.status_code == 413
    assert response.json() == {"detail": "request_body_too_large"}

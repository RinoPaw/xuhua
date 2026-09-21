from __future__ import annotations

import asyncio

import heritage_explorer.assistant as assistant_module
from heritage_explorer.assistant import AssistantService
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class EmptySearch:
    def search(self, query: str, **kwargs):
        return SearchResponse((), 0)


class ChunkLLM:
    api_key = "configured"

    def __init__(self, chunks):
        self.chunks = tuple(chunks)

    async def stream_chat(self, messages, **kwargs):
        for chunk in self.chunks:
            yield chunk


def collect(generator):
    async def run():
        return [event async for event in generator]

    return asyncio.run(run())


def test_output_budget_truncates_and_completes(monkeypatch):
    monkeypatch.setattr(assistant_module, "AI_MAX_OUTPUT_CHARS", 5)
    events = collect(
        AssistantService(
            search=EmptySearch(),
            sessions=SessionStore(),
            llm=ChunkLLM(("abc", "defg", "never")),
        ).stream_turn("介绍一下非遗")
    )

    deltas = [
        event.payload["delta"] for event in events if event.type == "response.text.delta"
    ]
    assert deltas == ["abc", "de"]
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["answer"] == "abcde"


def test_response_timeout_without_text_is_terminal_failure(monkeypatch):
    class StalledLLM:
        api_key = "configured"

        async def stream_chat(self, messages, **kwargs):
            await asyncio.Event().wait()
            yield "never"

    monkeypatch.setattr(assistant_module, "AI_RESPONSE_TIMEOUT", 0.02)
    monkeypatch.setattr(assistant_module, "AI_FIRST_TOKEN_TIMEOUT", 1.0)
    events = collect(
        AssistantService(
            search=EmptySearch(), sessions=SessionStore(), llm=StalledLLM()
        ).stream_turn("介绍一下非遗")
    )

    assert events[-1].type == "turn.failed"
    assert events[-1].payload["code"] == "llm_response_timeout"
    assert not any(event.type == "turn.completed" for event in events)


def test_response_timeout_finalizes_already_streamed_text(monkeypatch):
    class PartialThenStalledLLM:
        api_key = "configured"

        async def stream_chat(self, messages, **kwargs):
            yield "已有回答"
            await asyncio.Event().wait()
            yield "never"

    monkeypatch.setattr(assistant_module, "AI_RESPONSE_TIMEOUT", 0.02)
    monkeypatch.setattr(assistant_module, "AI_FIRST_TOKEN_TIMEOUT", 1.0)
    events = collect(
        AssistantService(
            search=EmptySearch(), sessions=SessionStore(), llm=PartialThenStalledLLM()
        ).stream_turn("介绍一下非遗")
    )

    assert [
        event.payload["delta"] for event in events if event.type == "response.text.delta"
    ] == ["已有回答"]
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["answer"] == "已有回答"

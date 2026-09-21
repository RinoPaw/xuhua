from __future__ import annotations

import asyncio

from heritage_explorer.answer_policy import localized_copy
from heritage_explorer.assistant import AssistantService
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class _Search:
    def search(self, *_args, **_kwargs) -> SearchResponse:
        return SearchResponse(items=(), total=0)


class _EnglishLLM:
    api_key = "configured"

    def __init__(self) -> None:
        self.messages: list[list[dict[str, str]]] = []

    async def stream_chat(self, messages, **_kwargs):
        self.messages.append(messages)
        yield "Hi! What would you like to explore?"


def _collect(generator):
    async def run():
        return [event async for event in generator]

    return asyncio.run(run())


def test_english_question_uses_shared_assistant_pipeline_even_with_chinese_browser_hint() -> None:
    llm = _EnglishLLM()
    service = AssistantService(search=_Search(), sessions=SessionStore(), llm=llm)  # type: ignore[arg-type]

    events = _collect(
        service.stream_turn(
            "Tell me about Chinese shadow puppetry.",
            locale_hint="zh-CN",
        )
    )

    assert events[0].type == "turn.started"
    assert events[0].payload["locale"] == "en-US"
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["locale"] == "en-US"
    assert events[-1].payload["answer"] == "Hi! What would you like to explore?"
    assert "Reply in natural English" in llm.messages[0][0]["content"]


def test_english_greeting_uses_localized_fast_path_without_llm() -> None:
    llm = _EnglishLLM()
    service = AssistantService(search=_Search(), sessions=SessionStore(), llm=llm)  # type: ignore[arg-type]

    events = _collect(service.stream_turn("Hi there.", locale_hint="zh-CN"))

    assert events[0].type == "turn.started"
    assert events[0].payload["locale"] == "en-US"
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["locale"] == "en-US"
    assert events[-1].payload["answer"] == localized_copy("en-US", "greeting")
    assert llm.messages == []


def test_chinese_turn_keeps_the_existing_locale_on_the_same_pipeline() -> None:
    llm = _EnglishLLM()
    service = AssistantService(search=_Search(), sessions=SessionStore(), llm=llm)  # type: ignore[arg-type]

    events = _collect(service.stream_turn("讲讲非遗。", locale_hint="zh-CN"))

    assert events[0].payload["locale"] == "zh-CN"
    assert events[-1].payload["locale"] == "zh-CN"

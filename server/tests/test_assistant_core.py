from __future__ import annotations

import asyncio

import heritage_explorer.assistant as assistant_module
from heritage_explorer.assistant import AssistantService
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import SearchResponse
from heritage_explorer.providers.llm import OpenAICompatibleLLM
from heritage_explorer.sessions import SessionStore


class FakeSearch:
    def __init__(self, items=()):
        self.items = tuple(items)

    def search(self, query: str, **kwargs):
        return SearchResponse(self.items, len(self.items))


class RecordingSearch(FakeSearch):
    def __init__(self, items=()):
        super().__init__(items)
        self.knowledge_base = KnowledgeBase(
            {
                "items": [
                    {
                        "id": "item-1",
                        "title": "传统插花",
                        "category": "传统美术",
                        "level": "国家级",
                    }
                ]
            }
        )
        self.calls = []

    def search(self, query: str, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return super().search(query, **kwargs)


class FakeLLM:
    def __init__(self, chunks=("# 标题", "\n\n正文")):
        self.chunks = chunks
        self.messages = []

    async def stream_chat(self, messages, **kwargs):
        self.messages.append(messages)
        for chunk in self.chunks:
            yield chunk


def collect(generator):
    async def run():
        return [event async for event in generator]

    return asyncio.run(run())


def test_turn_events_are_ordered_and_markdown_is_not_json_parsed():
    llm = FakeLLM()
    service = AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm)
    events = collect(service.stream_turn("介绍一下非遗"))

    assert [event.seq for event in events] == list(range(len(events)))
    assert {event.session_id for event in events}
    assert events[-1].type == "turn.completed"
    assert events[-1].payload["answer"] == "# 标题\n\n正文"
    source_event = next(event for event in events if event.type == "response.sources")
    assert source_event.payload["sources"] == []


def test_candidate_width_follows_intent_requested_count_and_exact_match():
    search = RecordingSearch()
    service = AssistantService(search=search, sessions=SessionStore(), llm=FakeLLM())

    collect(service.stream_turn("有哪些传统美术项目值得了解？"))
    assert search.calls[-1]["limit"] == 12

    collect(service.stream_turn("推荐5个传统美术项目"))
    assert search.calls[-1]["limit"] == 7

    collect(service.stream_turn("介绍传统插花"))
    assert search.calls[-1]["limit"] == 1


def test_broad_category_browse_uses_a_turn_specific_catalogue_window():
    class CatalogueSearch(RecordingSearch):
        def __init__(self):
            super().__init__()
            self.knowledge_base = KnowledgeBase(
                {
                    "categories": [{"id": 7, "name": "传统美术", "item_count": 417}],
                    "items": [],
                }
            )

        def search(self, query: str, **kwargs):
            self.calls.append({"query": query, **kwargs})
            return SearchResponse((), 417)

    search = CatalogueSearch()
    service = AssistantService(search=search, sessions=SessionStore(), llm=FakeLLM())

    collect(service.stream_turn("有哪些传统美术项目值得了解？", turn_id="turn-a"))

    assert len(search.calls) == 2
    assert search.calls[0]["limit"] == 12
    assert 0 < search.calls[1]["offset"] <= 405


def test_greeting_is_short_and_does_not_search_or_call_the_llm():
    class NoSearch:
        def search(self, query: str, **kwargs):
            raise AssertionError("a greeting must not enter retrieval")

    llm = FakeLLM()
    events = collect(
        AssistantService(search=NoSearch(), sessions=SessionStore(), llm=llm).stream_turn("你好。")
    )

    assert events[-1].type == "turn.completed"
    assert events[-1].payload["answer"] == "你好。想了解哪项非遗？"
    assert llm.messages == []


def test_multilingual_greetings_are_localized_without_entering_retrieval():
    class NoSearch:
        def search(self, query: str, **kwargs):
            raise AssertionError("a greeting must not enter retrieval")

    llm = FakeLLM()
    service = AssistantService(search=NoSearch(), sessions=SessionStore(), llm=llm)

    english = collect(service.stream_turn("Hello", locale_hint="en-US"))
    japanese = collect(service.stream_turn("こんにちは", locale_hint="ja-JP"))
    henan = collect(service.stream_turn("恁好", locale_hint="zh-CN"))

    assert english[-1].payload["locale"] == "en-US"
    assert english[-1].payload["answer"].startswith("Hello.")
    assert japanese[-1].payload["locale"] == "ja-JP"
    assert japanese[-1].payload["answer"].startswith("こんにちは。")
    assert henan[-1].payload["locale"] == "zh-CN-henan"
    assert henan[-1].payload["answer"].startswith("恁好。")
    assert llm.messages == []


def test_foreign_language_query_is_bridged_to_the_chinese_catalogue():
    search = RecordingSearch()
    llm = FakeLLM(("Kunqu (昆曲) is a refined form of Chinese theatre.",))
    service = AssistantService(search=search, sessions=SessionStore(), llm=llm)

    events = collect(service.stream_turn("Tell me about Kunku opera", locale_hint="en-US"))

    assert search.calls[0]["query"] == "昆曲"
    assert events[0].payload["locale"] == "en-US"
    assert events[-1].payload["locale"] == "en-US"
    assert "Reply in natural English" in llm.messages[0][0]["content"]
    assert "canonical Chinese name" in llm.messages[0][0]["content"]


def test_japanese_and_korean_asr_variants_recover_the_canonical_project_name():
    search = RecordingSearch()
    service = AssistantService(search=search, sessions=SessionStore(), llm=FakeLLM())

    collect(service.stream_turn("根極という伝統芸術を紹介してください", locale_hint="ja-JP"))
    collect(service.stream_turn("곤국이라는 전통 예술을 소개해 주세요", locale_hint="ko-KR"))

    assert [call["query"] for call in search.calls] == ["昆曲", "昆曲"]


def test_henan_dialect_is_kept_in_the_answer_instruction_without_changing_facts():
    search = RecordingSearch()
    llm = FakeLLM(("中，咱从河南剪纸聊起。",))
    service = AssistantService(search=search, sessions=SessionStore(), llm=llm)

    events = collect(service.stream_turn("恁讲讲河南剪纸中不中", locale_hint="zh-CN"))

    assert events[-1].payload["locale"] == "zh-CN-henan"
    assert "自然、克制、易懂的河南口吻" in llm.messages[0][0]["content"]


def test_broad_multilingual_heritage_query_opens_a_bounded_catalogue_window():
    search = RecordingSearch()
    service = AssistantService(search=search, sessions=SessionStore(), llm=FakeLLM())

    collect(service.stream_turn("中国の無形文化遺産を紹介して", locale_hint="ja-JP"))

    assert search.calls[0]["query"] == ""
    assert search.calls[0]["limit"] == service.max_candidates


def test_ambiguous_first_turn_does_not_retrieve_or_invent_user_mentions():
    class NoWeakSearch(RecordingSearch):
        def search(self, query: str, **kwargs):
            raise AssertionError("an ungrounded transcript must not enter retrieval")

    search = NoWeakSearch()
    llm = FakeLLM(("我没听清这句话。", "你可以再说一次想聊的对象。"))
    service = AssistantService(search=search, sessions=SessionStore(), llm=llm)

    events = collect(service.stream_turn("需要是他是觉得。他说。", session_id="fresh-page"))

    retrieval = next(event for event in events if event.type == "retrieval.completed")
    assert retrieval.payload == {"total": 0, "source_count": 0}
    assert "没有识别到明确的非遗项目" in llm.messages[0][1]["content"]
    assert "传统插花" not in "\n".join(message["content"] for message in llm.messages[0])
    assert events[-1].payload["answer"] == "我没听清这句话。你可以再说一次想聊的对象。"


def test_empty_llm_key_uses_local_fallback_without_constructing_network_request():
    class RaisingClient:
        def stream(self, *args, **kwargs):
            raise AssertionError("network must not be attempted")

    provider = OpenAICompatibleLLM(
        api_key="", base_url="https://example.invalid", model="x", client=RaisingClient()
    )
    events = collect(
        AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=provider).stream_turn(
            "tell me more"
        )
    )

    assert events[-1].type == "turn.completed"
    assert any(event.type == "response.text.delta" for event in events)
    assert not any(event.type == "warning" for event in events)


def test_provider_failure_is_an_explicit_terminal_failure():
    class BrokenLLM:
        async def stream_chat(self, messages, **kwargs):
            raise RuntimeError("offline")
            yield "never"

    events = collect(
        AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=BrokenLLM()).stream_turn(
            "tell me more"
        )
    )

    assert events[-1].type == "turn.failed"
    assert events[-1].payload["code"] == "llm_unavailable"
    assert not any(event.type == "turn.completed" for event in events)


def test_first_token_timeout_closes_old_stream_before_one_retry(monkeypatch):
    class SlowThenFastLLM:
        api_key = "configured"

        def __init__(self):
            self.calls = 0
            self.first_closed = asyncio.Event()
            self.second_started = asyncio.Event()

        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                try:
                    await asyncio.Event().wait()
                    yield "unreachable"
                finally:
                    self.first_closed.set()
                return
            self.second_started.set()
            assert self.first_closed.is_set()
            yield "重试成功"

    monkeypatch.setattr(assistant_module, "AI_FIRST_TOKEN_TIMEOUT", 0.01)
    llm = SlowThenFastLLM()
    events = collect(
        AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn(
            "tell me more"
        )
    )

    assert llm.calls == 2
    assert llm.second_started.is_set()
    assert [
        event.payload.get("delta") for event in events if event.type == "response.text.delta"
    ] == ["重试成功"]
    assert events[-1].type == "turn.completed"


def test_failure_after_delta_is_not_replayed_or_retried():
    class PartialThenBrokenLLM:
        api_key = "configured"

        def __init__(self):
            self.calls = 0

        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            yield "已有片段"
            raise RuntimeError("connection lost")

    llm = PartialThenBrokenLLM()
    events = collect(
        AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn(
            "tell me more"
        )
    )

    assert llm.calls == 1
    assert [
        event.payload.get("delta") for event in events if event.type == "response.text.delta"
    ] == ["已有片段"]
    assert events[-1].type == "turn.failed"
    assert events[-1].payload["code"] == "llm_unavailable"


def test_empty_configured_stream_is_retried_then_fails(monkeypatch):
    class EmptyLLM:
        api_key = "configured"

        def __init__(self):
            self.calls = 0

        async def stream_chat(self, messages, **kwargs):
            self.calls += 1
            if False:
                yield "never"

    monkeypatch.setattr(assistant_module, "AI_FIRST_TOKEN_TIMEOUT", 0.01)
    llm = EmptyLLM()
    events = collect(
        AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn(
            "tell me more"
        )
    )

    assert llm.calls == 2
    assert events[-1].type == "turn.failed"
    assert events[-1].payload == {"code": "llm_empty_stream", "attempts": 2}


def test_invalid_input_has_one_explicit_terminal_event():
    service = AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=FakeLLM())

    empty = collect(service.stream_turn("  \n  "))
    too_long = collect(service.stream_turn("问" * 4001))

    assert [event.type for event in empty] == ["turn.failed"]
    assert empty[0].payload == {"code": "empty_question"}
    assert [event.type for event in too_long] == ["turn.failed"]
    assert too_long[0].payload == {"code": "question_too_long", "max_chars": 4000}

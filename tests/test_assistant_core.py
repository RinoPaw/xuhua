from __future__ import annotations

import asyncio

import heritage_explorer.assistant as assistant_module
from heritage_explorer.assistant import (
    AssistantService,
    _fallback_answer,
    _retrieval_basis,
    _suggestions,
    _used_sources,
)
from heritage_explorer.models import AssistantEvent, ConversationTurn, SearchResponse
from heritage_explorer.providers.llm import OpenAICompatibleLLM
from heritage_explorer.sessions import SessionStore
from heritage_explorer.dataset import KnowledgeBase


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
            self.knowledge_base = KnowledgeBase({
                "categories": [{"id": 7, "name": "传统美术", "item_count": 417}],
                "items": [],
            })

        def search(self, query: str, **kwargs):
            self.calls.append({"query": query, **kwargs})
            return SearchResponse((), 417)

    search = CatalogueSearch()
    service = AssistantService(search=search, sessions=SessionStore(), llm=FakeLLM())

    collect(service.stream_turn("有哪些传统美术项目值得了解？", turn_id="turn-a"))

    assert len(search.calls) == 2
    assert search.calls[0]["limit"] == 12
    assert 0 < search.calls[1]["offset"] <= 405


def test_sources_and_suggestions_follow_projects_named_in_answer():
    items = tuple(
        type("Item", (), {"id": id_, "title": title, "family": "", "display_forms": (), "category": "", "summary": "", "content": "", "search_text": "", "level": "", "province": "", "city": "", "district": "", "suitable_scenarios": ()})()
        for id_, title in (("a", "甲项目"), ("b", "乙项目"), ("c", "丙项目"))
    )
    used = _used_sources("先看看乙项目，再比较甲项目。", items)
    assert [item.id for item in used] == ["b", "a"]
    assert [text.split("的", 1)[0] for text in _suggestions(used)] == ["乙项目", "甲项目", "按地区继续比较"]
    assert [item.id for item in _used_sources("没有点名具体项目。", items)] == ["a"]

    shared_family = tuple(
        type("Item", (), {"id": id_, "title": title, "family": "剪纸", "display_forms": ()})()
        for id_, title in (("paper-a", "甲地剪纸"), ("paper-b", "乙地剪纸"))
    )
    assert [item.id for item in _used_sources("剪纸讲究以形写神，先看甲地剪纸。", shared_family)] == ["paper-a"]


def test_local_fallback_selection_is_driven_by_request_and_content_budget():
    def make_items(summary: str):
        return tuple(
            type("Item", (), {"title": f"项目{index}", "summary": summary, "content": ""})()
            for index in range(1, 9)
        )

    long_answer = _fallback_answer("有哪些项目值得了解？", make_items("长" * 180))
    short_answer = _fallback_answer("有哪些项目值得了解？", make_items("短" * 20))
    requested_answer = _fallback_answer("推荐2个项目", make_items("长" * 180))

    assert long_answer.count("**项目") == 4
    assert short_answer.count("**项目") == 6
    assert requested_answer.count("**项目") == 2


def test_greeting_is_short_and_does_not_search_or_call_the_llm():
    class NoSearch:
        def search(self, query: str, **kwargs):
            raise AssertionError("a greeting must not enter retrieval")

    llm = FakeLLM()
    events = collect(AssistantService(search=NoSearch(), sessions=SessionStore(), llm=llm).stream_turn("你好。"))

    assert events[-1].type == "turn.completed"
    assert events[-1].payload["answer"] == "你好。想了解哪项非遗？"
    assert llm.messages == []


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
    assert _retrieval_basis(search, "需要是他是觉得。他说。") == "none"
    assert _retrieval_basis(search, "介绍传统插花") == "item_name"
    assert "没有识别到明确的非遗项目" in llm.messages[0][1]["content"]
    assert "传统插花" not in "\n".join(message["content"] for message in llm.messages[0])
    assert events[-1].payload["answer"] == "我没听清这句话。你可以再说一次想聊的对象。"


def test_cancelled_turn_does_not_write_history():
    store = SessionStore()
    session = store.get_or_create("session")
    _, turn_id, _ = store.begin_turn(session.session_id, "turn")
    assert store.cancel_turn(session.session_id, turn_id)
    assert store.cancel_turn(session.session_id, "missing") is False
    store.finish_turn(session.session_id, turn_id)
    assert store.history(session.session_id) == []


def test_session_capacity_evicts_oldest_idle_session():
    store = SessionStore(max_sessions=2)
    first = store.get_or_create("first")
    store.get_or_create("second")
    first.last_seen -= 10
    store.get_or_create("third")
    assert store.get("first") is None
    assert store.size() == 2


def test_event_has_stable_nested_envelope_and_timestamp():
    event = AssistantEvent("warning", "session", "turn", 3, payload={"code": "offline"})
    payload = event.to_dict()
    assert set(payload) == {"type", "session_id", "turn_id", "seq", "timestamp", "payload"}
    assert payload["payload"] == {"code": "offline"}


def test_new_turn_cancels_previous_turn_without_reusing_finish_cleanup():
    store = SessionStore()
    _, old_id, old_event = store.begin_turn("session", "old")
    _, new_id, new_event = store.begin_turn("session", "new")
    assert old_id == "old" and new_id == "new"
    assert old_event.is_set() and store.cancel_reason("session", "old") == "superseded"
    assert not new_event.is_set()
    store.finish_turn("session", old_id, old_event)
    assert "new" in store.get("session").active_turns


def test_active_sessions_are_not_evicted_or_expired_when_over_capacity():
    store = SessionStore(max_sessions=1, ttl_seconds=0.01)
    session, turn_id, event = store.begin_turn("active", "turn")
    session.last_seen -= 10
    _, second_id, second_event = store.begin_turn("second", "turn")
    assert store.get("active") is not None
    assert store.size() == 2
    store.finish_turn("active", turn_id, event)
    store.finish_turn("second", second_id, second_event)
    assert store.size() == 1


def test_history_returns_thread_safe_snapshot_and_is_bounded():
    store = SessionStore(max_turns=2)
    for index in range(3):
        store.append("session", ConversationTurn(str(index), "q", "a"))
    history = store.history("session")
    assert [turn.turn_id for turn in history] == ["1", "2"]
    history.clear()
    assert len(store.history("session")) == 2


def test_prompt_preserves_real_speaker_roles_and_separates_retrieval_context():
    service = AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=FakeLLM())
    messages = service._messages(
        "嗯。",
        (),
        [ConversationTurn("turn", "介绍一下锅庄舞", "锅庄舞有圆圈舞的形态。")],
    )

    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "system", "system", "system", "user",
    ]
    assert messages[1]["content"] == "介绍一下锅庄舞"
    assert messages[2]["content"] == "锅庄舞有圆圈舞的形态。"
    assert "不是用户说的话" in messages[3]["content"]
    assert "同时用于字幕和 TTS 的台词" in messages[0]["content"]
    assert "不书写动作、神态、语气标签、旁白或括号舞台说明" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "嗯。"}
    assert any("简短回应" in message["content"] for message in messages)


def test_short_reply_keeps_previous_assistant_words_owned_by_assistant():
    service = AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=FakeLLM())
    messages = service._messages(
        "嗯。",
        (),
        [ConversationTurn(
            "turn",
            "介绍锅庄舞",
            "我刚才讲了赉谟卓干玛和甘孜锅庄的不同气质。",
        )],
        short_reply_mode="continuation",
    )

    assert messages[-1] == {"role": "user", "content": "嗯。"}
    assert messages[2]["role"] == "assistant"
    assert "assistant" in messages[0]["content"]
    assert any("用户本轮只是简短回应" in message["content"] for message in messages)


def test_empty_llm_key_uses_local_fallback_without_constructing_network_request():
    class RaisingClient:
        def stream(self, *args, **kwargs):
            raise AssertionError("network must not be attempted")

    provider = OpenAICompatibleLLM(api_key="", base_url="https://example.invalid", model="x", client=RaisingClient())
    events = collect(AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=provider).stream_turn("hello"))
    assert events[-1].type == "turn.completed"
    assert any(event.type == "response.text.delta" for event in events)
    assert not any(event.type == "warning" for event in events)


def test_provider_failure_is_an_explicit_terminal_failure():
    class BrokenLLM:
        async def stream_chat(self, messages, **kwargs):
            raise RuntimeError("offline")
            yield "never"

    events = collect(AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=BrokenLLM()).stream_turn("hello"))
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
    events = collect(AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn("hello"))

    assert llm.calls == 2
    assert llm.second_started.is_set()
    assert [event.payload.get("delta") for event in events if event.type == "response.text.delta"] == ["重试成功"]
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
    events = collect(AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn("hello"))

    assert llm.calls == 1
    assert [event.payload.get("delta") for event in events if event.type == "response.text.delta"] == ["已有片段"]
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
    events = collect(AssistantService(search=FakeSearch(), sessions=SessionStore(), llm=llm).stream_turn("hello"))

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

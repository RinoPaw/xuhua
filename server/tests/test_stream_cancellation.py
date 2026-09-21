from __future__ import annotations

import asyncio

from heritage_explorer.assistant import AssistantService
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class EmptySearch:
    def search(self, query: str, **kwargs: object) -> SearchResponse:
        return SearchResponse((), 0)


class DisabledLLM:
    api_key = ""

    async def stream_chat(self, messages: object, **kwargs: object):
        raise AssertionError("disabled LLM must not be called")
        yield "unreachable"


class FirstCallBlocks:
    def __init__(self) -> None:
        self.calls = 0
        self.first_started = asyncio.Event()
        self.first_closed = asyncio.Event()

    async def stream_chat(self, messages: object, **kwargs: object):
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            try:
                await asyncio.Event().wait()
                yield "unreachable"
            finally:
                self.first_closed.set()
            return
        yield "第二个回答"


def test_superseding_turn_closes_blocked_provider_stream() -> None:
    async def scenario() -> None:
        llm = FirstCallBlocks()
        store = SessionStore()
        service = AssistantService(search=EmptySearch(), sessions=store, llm=llm)

        async def collect(question: str, turn_id: str):
            return [
                event
                async for event in service.stream_turn(
                    question,
                    session_id="session",
                    turn_id=turn_id,
                )
            ]

        first = asyncio.create_task(collect("第一个问题", "first"))
        await asyncio.wait_for(llm.first_started.wait(), timeout=1)
        second_events = await asyncio.wait_for(collect("第二个问题", "second"), timeout=1)
        first_events = await asyncio.wait_for(first, timeout=1)

        assert first_events[-1].type == "turn.cancelled"
        assert first_events[-1].payload["reason"] == "superseded"
        assert llm.first_closed.is_set()
        assert second_events[-1].type == "turn.completed"
        assert [turn.turn_id for turn in store.history("session")] == ["second"]

    asyncio.run(scenario())


def test_same_turn_id_supersession_preserves_old_generation_reason() -> None:
    async def scenario() -> None:
        llm = FirstCallBlocks()
        store = SessionStore()
        service = AssistantService(search=EmptySearch(), sessions=store, llm=llm)

        async def collect(question: str):
            return [
                event
                async for event in service.stream_turn(
                    question,
                    session_id="session",
                    turn_id="same",
                )
            ]

        first = asyncio.create_task(collect("第一个问题"))
        await asyncio.wait_for(llm.first_started.wait(), timeout=1)
        replacement_events = await asyncio.wait_for(collect("第二个问题"), timeout=1)
        first_events = await asyncio.wait_for(first, timeout=1)

        assert first_events[-1].type == "turn.cancelled"
        assert first_events[-1].payload["reason"] == "superseded"
        assert replacement_events[-1].type == "turn.completed"
        history = store.history("session")
        assert len(history) == 1
        assert history[0].question == "第二个问题"

    asyncio.run(scenario())


def test_supersession_after_sources_cancels_before_history_commit() -> None:
    async def scenario() -> None:
        store = SessionStore()
        service = AssistantService(
            search=EmptySearch(),
            sessions=store,
            llm=DisabledLLM(),
        )
        first = service.stream_turn(
            "介绍一下第一项非遗",
            session_id="session",
            turn_id="first",
        )

        first_events = []
        while True:
            event = await anext(first)
            first_events.append(event)
            if event.type == "response.sources":
                break

        replacement_events = [
            event
            async for event in service.stream_turn(
                "介绍一下第二项非遗",
                session_id="session",
                turn_id="second",
            )
        ]
        first_events.extend([event async for event in first])

        assert replacement_events[-1].type == "turn.completed"
        assert first_events[-1].type == "turn.cancelled"
        assert first_events[-1].payload["reason"] == "superseded"
        assert not any(event.type == "turn.completed" for event in first_events)
        history = store.history("session")
        assert len(history) == 1
        assert history[0].turn_id == "second"

    asyncio.run(scenario())


def test_transport_task_cancellation_propagates_and_releases_turn() -> None:
    async def scenario() -> None:
        llm = FirstCallBlocks()
        store = SessionStore()
        service = AssistantService(search=EmptySearch(), sessions=store, llm=llm)

        async def collect():
            return [
                event
                async for event in service.stream_turn(
                    "会被断开的请求",
                    session_id="session",
                    turn_id="transport-turn",
                )
            ]

        task = asyncio.create_task(collect())
        await asyncio.wait_for(llm.first_started.wait(), timeout=1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("transport cancellation must propagate")

        assert llm.first_closed.is_set()
        session = store.get("session")
        assert session is not None
        assert session.active_turns == {}
        assert store.history("session") == []

    asyncio.run(scenario())

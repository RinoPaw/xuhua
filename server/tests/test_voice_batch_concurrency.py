"""Deterministic ASR batch tests: out-of-order finish, cancel, and provider faults."""

from __future__ import annotations

import asyncio

import pytest

from heritage_explorer.admission import AdmissionController, AdmissionPolicy
from heritage_explorer.asr_normalization import NormalizedTranscript
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import AssistantEvent
from heritage_explorer.sessions import SessionStore
from heritage_explorer.voice import VoiceProviderError
from heritage_explorer.voice_events import (
    AssistantDoneEvent,
    UserPartialEvent,
    UserTranscriptEvent,
    UtteranceRejectedEvent,
    VoiceErrorEvent,
)
from heritage_explorer.voice_protocol import TextCommand, UtteranceStartCommand
from heritage_explorer.voice_session import VoiceSessionRuntime


class ControlledStream:
    def __init__(
        self,
        text: str,
        on_partial,
        *,
        finish_error: Exception | None = None,
        start_error: Exception | None = None,
    ) -> None:
        self.text = text
        self.on_partial = on_partial
        self.finish_error = finish_error
        self.start_error = start_error
        self.finish_started = asyncio.Event()
        self.finish_gate = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_count = 0
        self.candidates: tuple[str, ...] = ()
        self.detected_language = "zh"

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error

    async def send_audio(self, _data: bytes) -> None:
        return

    async def finish(self) -> str:
        self.finish_started.set()
        await self.finish_gate.wait()
        if self.finish_error is not None:
            raise self.finish_error
        return self.text

    async def close(self) -> None:
        self.close_count += 1
        self.closed.set()


class RecordingAssistant:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def stream_turn(
        self, question: str, *, session_id=None, turn_id=None, **_kwargs
    ):
        self.calls.append(question)
        yield AssistantEvent(
            "turn.completed",
            session_id or "voice-session",
            turn_id or "turn-id",
            0,
            payload={"answer": "回答完成", "locale": "zh-CN"},
        )


def make_runtime(
    specs: list[tuple[str, Exception | None, Exception | None]],
    *,
    stream_cls: type[ControlledStream] = ControlledStream,
) -> tuple[
    VoiceSessionRuntime,
    list[ControlledStream],
    list[object],
    RecordingAssistant,
    asyncio.Event,
    AdmissionController,
]:
    streams: list[ControlledStream] = []
    events: list[object] = []
    completed = asyncio.Event()
    assistant = RecordingAssistant()
    admission = AdmissionController({
        "chat": AdmissionPolicy(1, 100, 100),
        "asr": AdmissionPolicy(3, 100, 100),
    })

    async def emit(event: object) -> None:
        events.append(event)
        if isinstance(event, (AssistantDoneEvent, VoiceErrorEvent, UtteranceRejectedEvent)):
            completed.set()

    def stream_factory(**kwargs) -> ControlledStream:
        text, finish_error, start_error = specs[len(streams)]
        stream = stream_cls(
            text,
            kwargs["on_partial"],
            finish_error=finish_error,
            start_error=start_error,
        )
        streams.append(stream)
        return stream

    runtime = VoiceSessionRuntime(
        emit=emit,
        connection_id="batch-race",
        assistant=assistant,  # type: ignore[arg-type]
        sessions=SessionStore(),
        knowledge_base=KnowledgeBase({"categories": [], "items": []}),
        app_id="test", api_key="test", api_secret="test",
        asr_host="test.invalid",
        stream_factory=stream_factory,
        normalize_final=lambda text, **_kwargs: NormalizedTranscript(text, text, ()),
        max_session_id_chars=128,
        admission=admission,
        client_id="test-client",
    )
    return runtime, streams, events, assistant, completed, admission


def test_out_of_order_finalizers_commit_one_ordered_batch() -> None:
    async def scenario() -> None:
        runtime, streams, events, assistant, completed, admission = make_runtime(
            [("第一段", None, None), ("第二段", None, None)]
        )
        try:
            for _ in range(2):
                await runtime.handle_utterance_start(UtteranceStartCommand())
                await runtime.handle_utterance_end()
            assert len(streams) == 2
            await asyncio.wait_for(
                asyncio.gather(*(stream.finish_started.wait() for stream in streams)),
                timeout=2,
            )

            # Second ASR completes first, but the first finalizer still owns
            # the same batch and prevents any partial question from committing.
            streams[1].finish_gate.set()
            await asyncio.wait_for(streams[1].closed.wait(), timeout=2)
            assert assistant.calls == []
            assert not any(isinstance(e, UserTranscriptEvent) for e in events)

            streams[0].finish_gate.set()
            await asyncio.wait_for(completed.wait(), timeout=2)
            transcripts = [e for e in events if isinstance(e, UserTranscriptEvent)]
            assert len(transcripts) == 1
            assert transcripts[0].utterance_id == 2
            assert transcripts[0].text == "第一段 第二段"
            assert assistant.calls == ["第一段 第二段"]
            assert all(stream.close_count == 1 for stream in streams)
        finally:
            await runtime.close()
        assert admission._active["asr"] == 0
        assert admission._active["chat"] == 0

    asyncio.run(scenario())


def test_cancelling_finalizer_prevents_late_transcript_and_releases_lease() -> None:
    async def scenario() -> None:
        runtime, streams, events, assistant, completed, admission = make_runtime(
            [("已取消的录音", None, None)]
        )
        try:
            await runtime.handle_utterance_start(UtteranceStartCommand())
            await runtime.handle_utterance_end()
            await asyncio.wait_for(streams[0].finish_started.wait(), timeout=2)
            old_generation = runtime.batch.generation

            # Typed input clears and cancels the pending ASR batch.
            await runtime.handle_text(TextCommand("新的文字提问", "a" * 32))
            await asyncio.wait_for(completed.wait(), timeout=2)
            assert runtime.batch.generation > old_generation
            assert streams[0].close_count == 1
            assert assistant.calls == ["新的文字提问"]
            assert not any(isinstance(e, UserTranscriptEvent) for e in events)

            # Provider callback from the old generation must not publish a
            # partial, even if it arrives after the new answer has started.
            await streams[0].on_partial("迟到的识别结果")
            streams[0].finish_gate.set()
            await asyncio.sleep(0)
            assert not any(isinstance(e, UserPartialEvent) for e in events)
            assert not any(isinstance(e, UserTranscriptEvent) for e in events)
        finally:
            await runtime.close()
        assert admission._active["asr"] == 0
        assert admission._active["chat"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_phase", ["start", "finish"])
@pytest.mark.parametrize("failure_type", [VoiceProviderError, RuntimeError])
def test_asr_provider_fault_always_emits_terminal_failure(
    failure_phase: str, failure_type: type[Exception]
) -> None:
    async def scenario() -> None:
        failure = failure_type("simulated provider failure")
        runtime, streams, events, assistant, completed, admission = make_runtime([
            (
                "unused",
                failure if failure_phase == "finish" else None,
                failure if failure_phase == "start" else None,
            )
        ])
        try:
            await runtime.handle_utterance_start(UtteranceStartCommand())
            await runtime.handle_utterance_end()
            if failure_phase == "finish":
                await asyncio.wait_for(streams[0].finish_started.wait(), timeout=2)
                streams[0].finish_gate.set()
            await asyncio.wait_for(completed.wait(), timeout=2)
            failures = [e for e in events if isinstance(e, VoiceErrorEvent)]
            assert len(failures) == 1
            assert failures[0].code == "asr_unavailable"
            assert failures[0].utterance_id == 1
            assert not any(isinstance(e, UserTranscriptEvent) for e in events)
            assert assistant.calls == []
            assert streams[0].close_count == 1
        finally:
            await runtime.close()
        assert admission._active["asr"] == 0

    asyncio.run(scenario())


def test_failed_asr_segment_does_not_poison_other_segment_out_of_order() -> None:
    async def scenario() -> None:
        runtime, streams, events, assistant, completed, admission = make_runtime(
            [
                ("", RuntimeError("recognizer crashed"), None),
                ("可用语音", None, None),
            ]
        )
        try:
            for _ in range(2):
                await runtime.handle_utterance_start(UtteranceStartCommand())
                await runtime.handle_utterance_end()
            await asyncio.wait_for(
                asyncio.gather(*(stream.finish_started.wait() for stream in streams)),
                timeout=2,
            )
            streams[1].finish_gate.set()
            await asyncio.wait_for(streams[1].closed.wait(), timeout=2)
            assert assistant.calls == []
            streams[0].finish_gate.set()
            await asyncio.wait_for(completed.wait(), timeout=2)
            transcripts = [e for e in events if isinstance(e, UserTranscriptEvent)]
            assert len(transcripts) == 1
            assert transcripts[0].text == "可用语音"
            assert not any(isinstance(e, VoiceErrorEvent) for e in events)
            assert assistant.calls == ["可用语音"]
        finally:
            await runtime.close()
        assert admission._active["asr"] == 0

    asyncio.run(scenario())



def test_sequential_successful_and_empty_batches_advance_generation_separately() -> None:
    async def scenario() -> None:
        runtime, streams, events, assistant, completed, admission = make_runtime([
            ("第一个问题", None, None),
            ("", None, None),
            ("第二个问题", None, None),
        ])
        try:
            starting_generation = runtime.batch.generation
            for index in range(3):
                completed.clear()
                await runtime.handle_utterance_start(UtteranceStartCommand())
                await runtime.handle_utterance_end()
                await asyncio.wait_for(streams[index].finish_started.wait(), timeout=2)
                streams[index].finish_gate.set()
                await asyncio.wait_for(completed.wait(), timeout=2)
                assert runtime.batch.generation == starting_generation + index + 1
                assert runtime.batch.partials == {}
                assert runtime.batch.pending == set()
                assert runtime.batch.results == {}

            transcripts = [e for e in events if isinstance(e, UserTranscriptEvent)]
            rejections = [e for e in events if isinstance(e, UtteranceRejectedEvent)]
            assert [(e.utterance_id, e.text) for e in transcripts] == [
                (1, "第一个问题"), (3, "第二个问题"),
            ]
            assert [e.utterance_id for e in rejections] == [2]
            assert assistant.calls == ["第一个问题", "第二个问题"]
            assert all(stream.close_count == 1 for stream in streams)
        finally:
            await runtime.close()
        assert admission._active["asr"] == 0
        assert admission._active["chat"] == 0

    asyncio.run(scenario())


class SlowCleanupStream(ControlledStream):
    """Mimic Xfyun final text arriving before its websocket closes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()

    async def finish_result(self) -> str:
        return await self.finish()

    async def close(self) -> None:
        self.close_count += 1
        self.close_started.set()
        await self.allow_close.wait()
        self.closed.set()


def test_final_transcript_and_answer_do_not_wait_for_slow_asr_close() -> None:
    async def scenario() -> None:
        runtime, streams, events, assistant, completed, admission = make_runtime(
            [("汴绣的历史", None, None)], stream_cls=SlowCleanupStream,
        )
        stream = streams[0] if streams else None
        try:
            await runtime.handle_utterance_start(UtteranceStartCommand())
            await runtime.handle_utterance_end()
            stream = streams[0]
            await asyncio.wait_for(stream.finish_started.wait(), timeout=2)
            stream.finish_gate.set()

            # The old implementation waited for the slow provider close
            # before emitting a final transcript or beginning the answer.
            await asyncio.wait_for(completed.wait(), timeout=2)
            assert assistant.calls == ["汴绣的历史"]
            assert any(isinstance(event, UserTranscriptEvent) for event in events)
            await asyncio.wait_for(stream.close_started.wait(), timeout=2)
            assert stream.closed.is_set() is False
            assert admission._active["asr"] == 1
            assert stream.close_count == 1

            stream.allow_close.set()
            await asyncio.wait_for(stream.closed.wait(), timeout=2)
        finally:
            if stream is not None:
                stream.allow_close.set()
            await runtime.close()
        assert admission._active["asr"] == 0
        assert admission._active["chat"] == 0

    asyncio.run(scenario())

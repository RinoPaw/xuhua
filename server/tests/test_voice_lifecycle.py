import asyncio

from heritage_explorer.admission import AdmissionController, AdmissionPolicy
from heritage_explorer.voice_lifecycle import MAX_ASR_OPERATIONS_PER_CONNECTION, VoiceConnectionScope


class RecordingStream:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FailingStream:
    def __init__(self) -> None:
        self.close_attempted = False

    async def close(self) -> None:
        self.close_attempted = True
        raise RuntimeError("cleanup failed")


def test_connection_scope_owns_answer_identity_and_task() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        scope = VoiceConnectionScope()
        task = scope.start_answer("turn-1", worker())
        owned = scope.active_turn_id == "turn-1" and scope.answer_task is task
        cleared_wrong = scope.clear_answer_if(asyncio.current_task(), "turn-1")
        await scope.cancel_answer()
        return owned, cleared_wrong, task.cancelled()

    assert asyncio.run(scenario()) == (True, False, True)


def test_connection_scope_detaches_asr_as_one_owned_resource() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        scope = VoiceConnectionScope()
        stream = RecordingStream()
        start_task = scope.start_asr(stream, worker())
        detached_stream, detached_start = scope.detach_asr()
        owned = detached_stream is stream and detached_start is start_task
        cleared = scope.asr_stream is None
        start_task.cancel()
        await asyncio.gather(start_task, return_exceptions=True)
        return owned, cleared, stream.closed

    assert asyncio.run(scenario()) == (True, True, False)


def test_cancel_asr_releases_owner_when_resource_close_fails() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        scope = VoiceConnectionScope()
        stream = FailingStream()
        start_task = scope.start_asr(stream, worker())

        await scope.cancel_asr()
        return start_task.cancelled(), stream.close_attempted, scope.asr_stream is None

    assert asyncio.run(scenario()) == (True, True, True)


def test_connection_scope_close_cancels_entire_resource_tree() -> None:
    async def scenario() -> tuple[bool, bool, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        scope = VoiceConnectionScope()
        stream = RecordingStream()
        answer = scope.start_answer("turn-1", worker())
        asr_start = scope.start_asr(stream, worker())
        finalizer = scope.start_finalizer(worker())

        await scope.close()
        return (
            answer.cancelled(),
            asr_start.cancelled(),
            finalizer.cancelled(),
            stream.closed,
        )

    assert asyncio.run(scenario()) == (True, True, True, True)

def test_answer_budget_is_released_even_if_task_never_starts() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"chat": AdmissionPolicy(1, 10, 10)})
        lease = await controller.acquire("chat", "one")
        scope = VoiceConnectionScope()

        async def blocked() -> None:
            await asyncio.Future()

        scope.start_answer("turn", blocked(), lease=lease)
        # No scheduling point between create_task and cancellation.
        await scope.cancel_answer()
        replacement = await controller.acquire("chat", "two")
        await replacement.release()

    asyncio.run(scenario())


def test_asr_capacity_counts_pending_finalizers_and_active_stream() -> None:
    async def scenario() -> None:
        scope = VoiceConnectionScope()
        gate = asyncio.Event()

        async def blocked() -> None:
            await gate.wait()

        for number in range(MAX_ASR_OPERATIONS_PER_CONNECTION):
            assert scope.can_start_asr()
            scope.start_finalizer(blocked(), name=f"asr-finalizer-{number}")

        assert scope.active_asr_operations == MAX_ASR_OPERATIONS_PER_CONNECTION
        assert not scope.can_start_asr()
        await scope.cancel_finalizers()
        assert scope.active_asr_operations == 0
        assert scope.can_start_asr()

    asyncio.run(scenario())



def test_cancel_finalizer_before_first_step_returns_asr_lease() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"asr": AdmissionPolicy(1, 10, 10)})
        scope = VoiceConnectionScope()
        stream = RecordingStream()
        lease = await controller.acquire("asr", "client-1")
        gate = asyncio.Event()

        async def pending() -> None:
            await gate.wait()

        scope.start_asr(stream, pending(), lease=lease)
        detached, start_task = scope.detach_asr()
        assert detached is stream
        start_task.cancel()
        await asyncio.gather(start_task, return_exceptions=True)
        scope.start_finalizer(pending())
        await scope.cancel_finalizers()

        assert stream.closed
        replacement = await controller.acquire("asr", "client-2")
        await replacement.release()

    asyncio.run(scenario())


def test_asr_close_failure_still_returns_admission_slot() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"asr": AdmissionPolicy(1, 10, 10)})
        scope = VoiceConnectionScope()
        lease = await controller.acquire("asr", "client-1")
        stream = FailingStream()

        async def pending() -> None:
            await asyncio.Future()

        scope.start_asr(stream, pending(), lease=lease)
        await scope.cancel_asr()
        assert stream.close_attempted
        replacement = await controller.acquire("asr", "client-2")
        await replacement.release()

    asyncio.run(scenario())



def test_voice_lifecycle_logs_each_budget_release_once(caplog) -> None:
    import logging

    async def scenario() -> None:
        tick = [1.0]
        controller = AdmissionController({
            "chat": AdmissionPolicy(1, 10, 10),
            "asr": AdmissionPolicy(1, 10, 10),
        })
        scope = VoiceConnectionScope(connection_id="trace-conn", clock=lambda: tick[0])

        async def blocked() -> None:
            await asyncio.Future()

        chat_lease = await controller.acquire("chat", "client")
        scope.start_answer("trace-turn", blocked(), lease=chat_lease)
        tick[0] += 0.025
        await scope.cancel_answer()
        again = await controller.acquire("chat", "other")
        await again.release()

        asr_lease = await controller.acquire("asr", "client")
        stream = RecordingStream()
        scope.start_asr(stream, blocked(), lease=asr_lease, utterance_id=7)
        tick[0] += 0.050
        await scope.cancel_asr()
        await scope.release_asr(stream, label="voice.asr.duplicate")
        again = await controller.acquire("asr", "other")
        await again.release()
        assert stream.closed

    with caplog.at_level(logging.INFO, logger="heritage_explorer.voice_lifecycle"):
        asyncio.run(scenario())

    lines = [record.message for record in caplog.records]
    chat = [line for line in lines if line.startswith("voice.chat.release")]
    asr = [line for line in lines if line.startswith("voice.asr.release")]
    assert len(chat) == 1
    assert "connection=trace-conn turn=trace-turn held_ms=25.0" in chat[0]
    assert len(asr) == 1
    assert "connection=trace-conn utterance=7" in asr[0]
    assert "held_ms=50.0 remaining=0" in asr[0]



def test_connection_close_waits_for_finished_answers_in_flight_lease_release() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"chat": AdmissionPolicy(1, 10, 10)})
        underlying = await controller.acquire("chat", "first")
        release_started = asyncio.Event()
        release_allowed = asyncio.Event()

        class PausedLease:
            async def release(self) -> None:
                release_started.set()
                await release_allowed.wait()
                await underlying.release()

        scope = VoiceConnectionScope()

        async def answer() -> None:
            await scope.finish_answer(asyncio.current_task(), "turn")

        task = scope.start_answer("turn", answer(), lease=PausedLease())  # type: ignore[arg-type]
        await asyncio.wait_for(release_started.wait(), timeout=2)
        # The turn slot is already empty, but the chat budget is still held.
        assert scope.active_turn_id is None
        closing = asyncio.create_task(scope.close())
        await asyncio.sleep(0)
        assert not closing.done()
        assert controller._active["chat"] == 1

        release_allowed.set()
        await asyncio.wait_for(closing, timeout=2)
        await asyncio.gather(task, return_exceptions=True)
        assert controller._active["chat"] == 0
        next_lease = await controller.acquire("chat", "next")
        await next_lease.release()

    asyncio.run(scenario())


def test_cancel_during_answer_lease_release_joins_the_same_release() -> None:
    async def scenario() -> None:
        controller = AdmissionController({"chat": AdmissionPolicy(1, 10, 10)})
        underlying = await controller.acquire("chat", "first")
        release_started = asyncio.Event()
        release_allowed = asyncio.Event()
        release_calls = 0

        class PausedLease:
            async def release(self) -> None:
                nonlocal release_calls
                release_calls += 1
                release_started.set()
                await release_allowed.wait()
                await underlying.release()

        scope = VoiceConnectionScope()

        async def answer() -> None:
            await scope.finish_answer(asyncio.current_task(), "turn")

        scope.start_answer("turn", answer(), lease=PausedLease())  # type: ignore[arg-type]
        await asyncio.wait_for(release_started.wait(), timeout=2)
        cancelling = asyncio.create_task(scope.cancel_answer())
        await asyncio.sleep(0)
        assert not cancelling.done()

        release_allowed.set()
        await asyncio.wait_for(cancelling, timeout=2)
        assert release_calls == 1
        assert controller._active["chat"] == 0

    asyncio.run(scenario())

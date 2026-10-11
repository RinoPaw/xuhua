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

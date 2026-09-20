import asyncio

from heritage_explorer.voice_lifecycle import VoiceConnectionScope


class RecordingStream:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


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

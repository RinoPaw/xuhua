"""Connection-scoped ownership for realtime voice resources."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from .task_scope import TaskSet, TaskSlot, cancel_task


class VoiceConnectionScope:
    """Own all replaceable and background resources for one voice connection."""

    def __init__(self) -> None:
        self._answer = TaskSlot()
        self._answer_turn_id: str | None = None
        self._asr_start = TaskSlot()
        self._asr_stream: Any | None = None
        self._finalizers = TaskSet()

    @property
    def active_turn_id(self) -> str | None:
        return self._answer_turn_id

    @property
    def answer_task(self):
        return self._answer.task

    @property
    def asr_stream(self) -> Any | None:
        return self._asr_stream

    @property
    def finalizer_count(self) -> int:
        return len(self._finalizers.tasks)

    def start_answer(
        self,
        turn_id: str,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
    ):
        task = self._answer.create(awaitable, name=name)
        self._answer_turn_id = turn_id
        return task

    def take_answer(self):
        task = self._answer.take()
        turn_id, self._answer_turn_id = self._answer_turn_id, None
        return task, turn_id

    def clear_answer_if(self, task, turn_id: str) -> bool:
        if self._answer_turn_id != turn_id:
            return False
        if not self._answer.clear_if(task):
            return False
        self._answer_turn_id = None
        return True

    async def cancel_answer(self) -> None:
        task, _turn_id = self.take_answer()
        await cancel_task(task)

    def start_asr(
        self,
        stream: Any,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
    ):
        if self._asr_stream is not None:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            raise RuntimeError("asr_stream_busy")
        task = self._asr_start.create(awaitable, name=name)
        self._asr_stream = stream
        return task

    def detach_asr(self):
        stream, self._asr_stream = self._asr_stream, None
        return stream, self._asr_start.take()

    async def cancel_asr(self) -> None:
        stream, start_task = self.detach_asr()
        await cancel_task(start_task)
        if stream is not None:
            await stream.close()

    def start_finalizer(
        self,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
    ):
        return self._finalizers.create(awaitable, name=name)

    async def cancel_finalizers(self) -> None:
        await self._finalizers.cancel_all()

    async def close(self) -> None:
        """Close the full task/resource tree in deterministic dependency order."""

        await self.cancel_finalizers()
        await self.cancel_answer()
        await self.cancel_asr()


__all__ = ["VoiceConnectionScope"]

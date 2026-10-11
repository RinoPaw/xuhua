"""Connection-scoped ownership for realtime voice resources."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import time
from typing import Any

from .admission import AdmissionLease
from .task_scope import TaskSet, TaskSlot, cancel_task


LOGGER = logging.getLogger(__name__)
MAX_ASR_OPERATIONS_PER_CONNECTION = 3


async def close_resource(resource: Any | None, *, label: str) -> None:
    """Close one owned resource without letting provider cleanup failures escape."""

    if resource is None:
        return
    close = getattr(resource, "close", None)
    if close is None:
        return
    try:
        await close()
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.warning("%s.close_failed", label, exc_info=True)


class VoiceConnectionScope:
    """Own all replaceable and background resources for one voice connection."""

    def __init__(
        self,
        *,
        connection_id: str = "-",
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.connection_id = connection_id
        self._clock = clock
        self._answer_started_at: float | None = None
        self._answer_lease_turn_id: str | None = None
        self._answer = TaskSlot()
        self._answer_turn_id: str | None = None
        self._answer_lease: AdmissionLease | None = None
        self._asr_start = TaskSlot()
        self._asr_stream: Any | None = None
        # Own every stream until its finalizer finishes, even after detach_asr.
        self._asr_resources: dict[
            int, tuple[Any, AdmissionLease | None, int | None, float]
        ] = {}
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

    @property
    def active_asr_operations(self) -> int:
        """An ASR operation remains active while its finalizer is pending."""
        return int(self._asr_stream is not None) + sum(
            not task.done() for task in self._finalizers.tasks
        )

    def can_start_asr(self) -> bool:
        return self.active_asr_operations < MAX_ASR_OPERATIONS_PER_CONNECTION

    def start_answer(
        self,
        turn_id: str,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
        lease: AdmissionLease | None = None,
    ):
        task = self._answer.create(awaitable, name=name)
        self._answer_turn_id = turn_id
        self._answer_lease = lease
        self._answer_lease_turn_id = turn_id
        self._answer_started_at = self._clock()
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

    async def _release_answer_lease(self) -> None:
        lease, self._answer_lease = self._answer_lease, None
        turn_id, self._answer_lease_turn_id = self._answer_lease_turn_id, None
        started_at, self._answer_started_at = self._answer_started_at, None
        if lease is not None:
            try:
                await lease.release()
            finally:
                LOGGER.info(
                    "voice.chat.release connection=%s turn=%s held_ms=%.1f",
                    self.connection_id,
                    turn_id or "-",
                    max(0.0, (self._clock() - started_at) * 1000)
                    if started_at is not None
                    else 0.0,
                )

    async def finish_answer(self, task, turn_id: str) -> None:
        if self.clear_answer_if(task, turn_id):
            await self._release_answer_lease()

    async def cancel_answer(self) -> None:
        task, _turn_id = self.take_answer()
        try:
            await cancel_task(task)
        finally:
            # Cancellation before the task's first scheduling step never runs
            # its coroutine's finally block. The scope still owns the lease.
            await self._release_answer_lease()

    def start_asr(
        self,
        stream: Any,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
        lease: AdmissionLease | None = None,
        utterance_id: int | None = None,
    ):
        if self._asr_stream is not None:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            raise RuntimeError("asr_stream_busy")
        task = self._asr_start.create(awaitable, name=name)
        self._asr_stream = stream
        self._asr_resources[id(stream)] = (
            stream, lease, utterance_id, self._clock()
        )
        return task

    def detach_asr(self):
        stream, self._asr_stream = self._asr_stream, None
        return stream, self._asr_start.take()

    async def release_asr(self, stream: Any | None, *, label: str) -> None:
        """Return an operation's provider stream and its budget exactly once."""
        if stream is None:
            return
        owned = self._asr_resources.pop(id(stream), None)
        if owned is None:
            return
        resource, lease, utterance_id, started_at = owned
        try:
            await close_resource(resource, label=label)
        finally:
            try:
                if lease is not None:
                    await lease.release()
            finally:
                LOGGER.info(
                    "voice.asr.release connection=%s utterance=%s reason=%s "
                    "held_ms=%.1f remaining=%s",
                    self.connection_id,
                    utterance_id if utterance_id is not None else "-",
                    label,
                    max(0.0, (self._clock() - started_at) * 1000),
                    len(self._asr_resources),
                )

    async def cancel_asr(self) -> None:
        stream, start_task = self.detach_asr()
        try:
            await cancel_task(start_task)
        finally:
            await self.release_asr(stream, label="voice.asr")


    def start_finalizer(
        self,
        awaitable: Awaitable[None],
        *,
        name: str | None = None,
    ):
        return self._finalizers.create(awaitable, name=name)

    async def cancel_finalizers(self) -> None:
        try:
            await self._finalizers.cancel_all()
        finally:
            # A finalizer cancelled before its first execution never enters
            # finish_utterance's finally clause. The connection scope owns its
            # detached stream and lease independently of the task.
            detached = [
                resource
                for resource, _lease, _utterance_id, _started_at
                in self._asr_resources.values()
                if resource is not self._asr_stream
            ]
            for resource in detached:
                await self.release_asr(resource, label="voice.asr.cancelled")


    async def close(self) -> None:
        """Close the full task/resource tree in deterministic dependency order."""

        await self.cancel_finalizers()
        await self.cancel_answer()
        await self.cancel_asr()


__all__ = ["MAX_ASR_OPERATIONS_PER_CONNECTION", "VoiceConnectionScope", "close_resource"]

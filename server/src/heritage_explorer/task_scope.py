"""Small ownership primitives for connection-scoped asyncio tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
import inspect
import logging


LOGGER = logging.getLogger(__name__)


async def cancel_task(task: asyncio.Task[None] | None) -> None:
    """Cancel one owned task and always retrieve its terminal result."""

    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class TaskSlot:
    """Own at most one replaceable task."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    def create(self, awaitable: Awaitable[None], *, name: str | None = None) -> asyncio.Task[None]:
        current = self._task
        if current is not None and not current.done():
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("task_slot_busy")
        task = asyncio.create_task(awaitable, name=name)
        self._task = task
        return task

    def take(self) -> asyncio.Task[None] | None:
        task, self._task = self._task, None
        return task

    def clear_if(self, task: asyncio.Task[None] | None) -> bool:
        if task is None or self._task is not task:
            return False
        self._task = None
        return True

    async def cancel(self) -> None:
        await cancel_task(self.take())


class TaskSet:
    """Own a dynamic set of sibling background tasks."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def tasks(self) -> frozenset[asyncio.Task[None]]:
        return frozenset(self._tasks)

    def create(self, awaitable: Awaitable[None], *, name: str | None = None) -> asyncio.Task[None]:
        task = asyncio.create_task(awaitable, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            LOGGER.error(
                "background task failed",
                exc_info=(type(error), error, error.__traceback__),
            )

    async def cancel_all(self) -> None:
        tasks = tuple(self._tasks)
        self._tasks.clear()
        if tasks:
            await asyncio.gather(
                *(cancel_task(task) for task in tasks),
                return_exceptions=True,
            )


__all__ = ["TaskSet", "TaskSlot", "cancel_task"]

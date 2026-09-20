import asyncio

from heritage_explorer.task_scope import TaskSet, TaskSlot


def test_task_slot_owns_replaces_and_cancels_one_task() -> None:
    async def scenario() -> tuple[bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        slot = TaskSlot()
        first = slot.create(worker())
        busy = False
        try:
            slot.create(worker())
        except RuntimeError as error:
            busy = str(error) == "task_slot_busy"

        await slot.cancel()
        cancelled = first.cancelled()

        second = slot.create(worker())
        gate.set()
        await second
        slot.clear_if(second)
        return busy, cancelled

    assert asyncio.run(scenario()) == (True, True)


def test_task_set_tracks_siblings_and_cancels_them_together() -> None:
    async def scenario() -> tuple[int, bool, bool]:
        gate = asyncio.Event()

        async def worker() -> None:
            await gate.wait()

        tasks = TaskSet()
        first = tasks.create(worker())
        second = tasks.create(worker())
        tracked = len(tasks.tasks)
        await tasks.cancel_all()
        return tracked, first.cancelled(), second.cancelled()

    assert asyncio.run(scenario()) == (2, True, True)

from __future__ import annotations

import asyncio

from heritage_explorer.llm_stream import (
    LLMEmptyStream,
    LLMFirstTokenTimeout,
    close_iterator,
    stream_with_first_token_retry,
)


def collect(generator):
    async def run():
        return [item async for item in generator]

    return asyncio.run(run())


def test_empty_first_attempt_is_retried_before_any_text_is_emitted():
    attempts = 0

    async def factory_stream():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if False:
                yield ""
            return
        yield "第二次成功"

    cancel = asyncio.Event()
    result = collect(
        stream_with_first_token_retry(
            factory_stream,
            cancel,
            timeout=0.2,
            max_attempts=2,
            log_context="test",
        )
    )
    assert result == ["第二次成功"]
    assert attempts == 2


def test_timeout_reports_final_attempt_count():
    async def slow_stream():
        await asyncio.sleep(0.05)
        yield "太晚了"

    async def run():
        cancel = asyncio.Event()
        try:
            async for _ in stream_with_first_token_retry(
                slow_stream,
                cancel,
                timeout=0.005,
                max_attempts=2,
                log_context="test",
            ):
                pass
        except LLMFirstTokenTimeout as exc:
            return exc.attempts
        raise AssertionError("expected timeout")

    assert asyncio.run(run()) == 2


def test_empty_stream_reports_final_attempt_count():
    async def empty_stream():
        if False:
            yield ""

    async def run():
        cancel = asyncio.Event()
        try:
            async for _ in stream_with_first_token_retry(
                empty_stream,
                cancel,
                timeout=0.2,
                max_attempts=2,
                log_context="test",
            ):
                pass
        except LLMEmptyStream as exc:
            return exc.attempts
        raise AssertionError("expected empty stream")

    assert asyncio.run(run()) == 2


def test_cancel_event_stops_waiting_stream_without_emitting_text():
    async def slow_stream():
        await asyncio.sleep(1)
        yield "不会出现"

    async def run():
        cancel = asyncio.Event()

        async def trigger_cancel():
            await asyncio.sleep(0.01)
            cancel.set()

        task = asyncio.create_task(trigger_cancel())
        output = [
            item
            async for item in stream_with_first_token_retry(
                slow_stream,
                cancel,
                timeout=1,
                max_attempts=2,
                log_context="test",
            )
        ]
        await task
        return output

    assert asyncio.run(run()) == []


def test_iterator_close_is_bounded_when_provider_shutdown_is_slow():
    class SlowCloseIterator:
        async def aclose(self):
            await asyncio.sleep(0.2)

    async def run():
        loop = asyncio.get_running_loop()
        started = loop.time()
        await close_iterator(SlowCloseIterator(), timeout=0.01)
        return loop.time() - started

    assert asyncio.run(run()) < 0.1

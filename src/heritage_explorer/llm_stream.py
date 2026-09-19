"""LLM streaming helpers with bounded pre-first-token retry."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable

LOGGER = logging.getLogger(__name__)


class LLMFirstTokenTimeout(RuntimeError):
    def __init__(self, attempts: int) -> None:
        super().__init__("llm_first_token_timeout")
        self.attempts = attempts


class LLMEmptyStream(RuntimeError):
    def __init__(self, attempts: int) -> None:
        super().__init__("llm_empty_stream")
        self.attempts = attempts


async def close_iterator(iterator: object | None) -> None:
    if iterator is None:
        return
    close = getattr(iterator, "aclose", None)
    if close is not None:
        await close()


async def stream_with_first_token_retry(
    factory: Callable[[], AsyncIterator[str]],
    cancel_event: asyncio.Event,
    *,
    timeout: float,
    max_attempts: int,
    log_context: str,
) -> AsyncIterator[str]:
    """Retry only pre-first-token failures, closing each abandoned stream first."""

    attempts = min(max(int(max_attempts), 1), 2)
    first_token_timeout = max(float(timeout), 0.001)
    for attempt in range(1, attempts + 1):
        iterator: AsyncIterator[str] | None = None
        emitted = False
        started = time.perf_counter()
        LOGGER.info(
            "[%s] llm.attempt.start attempt=%s/%s first_token_timeout=%.3fs",
            log_context,
            attempt,
            attempts,
            first_token_timeout,
        )
        try:
            iterator = factory().__aiter__()
            while not cancel_event.is_set():
                remaining = None
                if not emitted:
                    remaining = first_token_timeout - (time.perf_counter() - started)
                    if remaining <= 0:
                        LOGGER.warning(
                            "[%s] llm.first-token-timeout attempt=%s/%s timeout=%.3fs",
                            log_context,
                            attempt,
                            attempts,
                            first_token_timeout,
                        )
                        raise LLMFirstTokenTimeout(attempt)

                next_task = asyncio.create_task(anext(iterator))
                cancelled = asyncio.create_task(cancel_event.wait())
                try:
                    done, _ = await asyncio.wait(
                        {next_task, cancelled},
                        timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        next_task.cancel()
                        await asyncio.gather(next_task, return_exceptions=True)
                        cancelled.cancel()
                        await asyncio.gather(cancelled, return_exceptions=True)
                        LOGGER.warning(
                            "[%s] llm.first-token-timeout attempt=%s/%s timeout=%.3fs",
                            log_context,
                            attempt,
                            attempts,
                            first_token_timeout,
                        )
                        raise LLMFirstTokenTimeout(attempt)
                    if cancelled in done and cancel_event.is_set():
                        next_task.cancel()
                        await asyncio.gather(next_task, return_exceptions=True)
                        return
                    cancelled.cancel()
                    await asyncio.gather(cancelled, return_exceptions=True)
                    try:
                        delta = next_task.result()
                    except StopAsyncIteration:
                        if not emitted:
                            raise LLMEmptyStream(attempt)
                        return
                finally:
                    for task in (next_task, cancelled):
                        if not task.done():
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)

                if not delta:
                    continue
                emitted = True
                yield delta
            return
        except (LLMFirstTokenTimeout, LLMEmptyStream) as exc:
            if emitted:
                raise
            if attempt >= attempts:
                raise
            LOGGER.info(
                "[%s] llm.retry attempt=%s/%s reason=%s",
                log_context,
                attempt,
                attempts,
                "first-token-timeout" if isinstance(exc, LLMFirstTokenTimeout) else "empty-stream",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            if emitted or attempt >= attempts:
                raise
            LOGGER.info(
                "[%s] llm.retry attempt=%s/%s reason=provider-failure",
                log_context,
                attempt,
                attempts,
            )
        finally:
            await close_iterator(iterator)


__all__ = [
    "LLMEmptyStream",
    "LLMFirstTokenTimeout",
    "close_iterator",
    "stream_with_first_token_retry",
]

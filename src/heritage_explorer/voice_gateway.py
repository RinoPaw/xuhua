"""Realtime browser voice transport for the assistant service."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
import logging
import time
import uuid
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .assistant import AssistantService
from .asr_normalization import NormalizedTranscript, normalize_asr_final
from .dataset import KnowledgeBase
from .language import (
    detect_locale,
    is_chinese_locale,
    locale_from_provider_language,
    normalize_locale_hint,
)
from .sessions import SessionStore
from .voice import VoiceProviderError, XfyunStream


MAX_VOICE_CONTEXT_TITLES = 8
MAX_VOICE_RECENT_ITEMS = 8
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def contains_spoken_text(value: object) -> bool:
    """Punctuation-only ASR hypotheses are not evidence of human speech."""

    return any(character.isalnum() for character in str(value or ""))


def register_voice_route(
    app: FastAPI,
    *,
    assistant: AssistantService,
    sessions: SessionStore,
    knowledge_base: KnowledgeBase,
    app_id: str,
    api_key: str,
    api_secret: str,
    asr_host: str,
    stream_factory: Callable[..., Any] = XfyunStream,
    max_session_id_chars: int = 128,
) -> None:
    """Register the continuous browser VAD + ASR + assistant WebSocket route."""

    @app.websocket("/api/voice")
    async def browser_voice(websocket: WebSocket) -> None:
        if not (app_id.strip() and api_key.strip() and api_secret.strip()):
            await websocket.close(code=1013, reason="voice_unavailable")
            return

        await websocket.accept()
        connection_id = uuid.uuid4().hex
        asr_stream: Any | None = None
        asr_start_task: asyncio.Task[None] | None = None
        answer_task: asyncio.Task[None] | None = None
        finalize_tasks: set[asyncio.Task[None]] = set()
        batch_results: dict[int, str] = {}
        batch_candidates: dict[int, tuple[str, ...]] = {}
        batch_languages: dict[int, str] = {}
        batch_failures: set[int] = set()
        batch_partials: dict[int, str] = {}
        pending_user_speaking: set[int] = set()
        partial_revision = 0
        batch_pending: set[int] = set()
        batch_generation = 0
        batch_lock = asyncio.Lock()
        session_id: str | None = None
        voice_category = ""
        voice_context_titles: list[str] = []
        voice_locale_hint = ""
        active_turn_id: str | None = None
        utterance_sequence = 0
        event_sequence = 0
        send_lock = asyncio.Lock()

        def update_voice_context(event: dict[str, Any]) -> None:
            nonlocal session_id, voice_category, voice_context_titles, voice_locale_hint
            category = str(event.get("category") or "").strip()
            voice_category = category[:200]
            incoming_session = str(event.get("session_id") or "").strip()
            if incoming_session:
                session_id = incoming_session[:max_session_id_chars]
            incoming_locale = normalize_locale_hint(event.get("locale_hint") or event.get("locale"))
            if incoming_locale:
                voice_locale_hint = incoming_locale

            values: list[Any] = []
            for key in ("selected_title", "selected_item", "selected"):
                value = event.get(key)
                if value:
                    values.append(value)
            for key in ("titles", "visible_titles", "visible_items", "items"):
                value = event.get(key)
                if isinstance(value, (list, tuple)):
                    values.extend(value)
            titles: list[str] = []
            seen: set[str] = set()
            for value in values:
                if isinstance(value, dict):
                    value = value.get("title", "")
                title = str(value or "").strip()
                if title and title not in seen:
                    seen.add(title)
                    titles.append(title[:200])
                if len(titles) >= MAX_VOICE_CONTEXT_TITLES:
                    break
            voice_context_titles = titles

        def recent_voice_items() -> tuple[Any, ...]:
            if not session_id:
                return ()
            recent: list[Any] = []
            seen: set[str] = set()
            for turn in reversed(sessions.history(session_id)):
                for source_id in reversed(turn.source_ids):
                    if source_id in seen:
                        continue
                    item = knowledge_base.get(source_id)
                    if item is not None:
                        seen.add(source_id)
                        recent.append(item)
                    if len(recent) >= MAX_VOICE_RECENT_ITEMS:
                        return tuple(recent)
            return tuple(recent)

        def make_asr_stream(on_partial: Any) -> Any:
            recent = recent_voice_items()
            recent_titles = [str(getattr(item, "title", "") or "") for item in recent]
            hotwords: list[str] = []
            seen: set[str] = set()
            for title in [voice_category, *voice_context_titles, *recent_titles]:
                title = title.strip()
                if title and title not in seen:
                    seen.add(title)
                    hotwords.append(title)
                if len(hotwords) >= MAX_VOICE_CONTEXT_TITLES + MAX_VOICE_RECENT_ITEMS:
                    break
            return stream_factory(
                app_id=app_id,
                api_key=api_key,
                api_secret=api_secret,
                host=asr_host,
                language="zh_cn",
                accent="mandarin",
                domain="slm",
                dynamic_correction=True,
                on_partial=on_partial,
                hotwords=tuple(hotwords),
            )

        async def send(payload: dict[str, Any]) -> None:
            nonlocal event_sequence
            try:
                async with send_lock:
                    event_sequence += 1
                    await websocket.send_json(
                        {
                            "connection_id": connection_id,
                            "sequence": event_sequence,
                            **payload,
                        }
                    )
            except (RuntimeError, WebSocketDisconnect):
                pass

        async def stop_task(task: asyncio.Task[None] | None) -> None:
            if task is None or task.done():
                return
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        async def stop_finalize_tasks() -> None:
            tasks = tuple(finalize_tasks)
            finalize_tasks.clear()
            if tasks:
                await asyncio.gather(*(stop_task(task) for task in tasks), return_exceptions=True)

        async def close_active_asr() -> None:
            nonlocal asr_stream, asr_start_task
            stream, asr_stream = asr_stream, None
            start_task, asr_start_task = asr_start_task, None
            if start_task is not None:
                if not start_task.done():
                    start_task.cancel()
                await asyncio.gather(start_task, return_exceptions=True)
            if stream is not None:
                await stream.close()

        def clear_voice_batch() -> None:
            nonlocal batch_generation, partial_revision
            batch_generation += 1
            batch_results.clear()
            batch_candidates.clear()
            batch_languages.clear()
            batch_failures.clear()
            batch_partials.clear()
            pending_user_speaking.clear()
            batch_pending.clear()
            partial_revision = 0

        def combined_partial_text() -> str:
            return " ".join(
                batch_partials[item_id].strip()
                for item_id in sorted(batch_partials)
                if batch_partials[item_id].strip()
            ).strip()

        async def send_batch_partial(utterance_id: int, text: str) -> None:
            nonlocal partial_revision
            if utterance_id not in batch_partials:
                return
            batch_partials[utterance_id] = str(text or "")
            combined = combined_partial_text()
            if not combined:
                return
            partial_revision += 1
            await send(
                {
                    "type": "user.partial",
                    "utterance_id": max(batch_partials),
                    "revision": partial_revision,
                    "text": combined,
                    "final": False,
                }
            )

        async def stop_answer(reason: str) -> None:
            nonlocal answer_task, active_turn_id
            task, turn_id = answer_task, active_turn_id
            answer_task = None
            active_turn_id = None
            if task is not None and not task.done():
                LOGGER.info(
                    "voice.answer.cancel connection=%s turn=%s reason=%s",
                    connection_id,
                    turn_id or "-",
                    reason,
                )
            await stop_task(task)

        async def answer(question: str, turn_id: str, locale_hint: str = "") -> None:
            nonlocal answer_task, active_turn_id, session_id
            answer_locale = detect_locale(question, hint=locale_hint or voice_locale_hint)
            LOGGER.info(
                "voice.agent.thinking connection=%s turn=%s question_chars=%s",
                connection_id,
                turn_id,
                len(question),
            )
            await send(
                {
                    "type": "status",
                    "status": "thinking",
                    "turn_id": turn_id,
                    "locale": answer_locale,
                }
            )
            try:
                async for event in assistant.stream_turn(
                    question,
                    session_id=session_id,
                    turn_id=turn_id,
                    category=voice_category,
                    locale_hint=answer_locale,
                ):
                    if active_turn_id != turn_id:
                        return
                    session_id = event.session_id
                    if event.type == "response.text.delta":
                        event_locale = str(event.payload.get("locale") or answer_locale)
                        await send(
                            {
                                "type": "assistant.delta",
                                "session_id": event.session_id,
                                "turn_id": event.turn_id,
                                "text": event.payload.get("delta", ""),
                                "locale": event_locale,
                            }
                        )
                    elif event.type == "response.sources":
                        await send(
                            {
                                "type": "sources",
                                "session_id": event.session_id,
                                "turn_id": event.turn_id,
                                "items": event.payload.get("sources", []),
                            }
                        )
                    elif event.type == "turn.completed":
                        event_locale = str(event.payload.get("locale") or answer_locale)
                        await send(
                            {
                                "type": "assistant.done",
                                "session_id": event.session_id,
                                "turn_id": event.turn_id,
                                "text": event.payload.get("answer", ""),
                                "locale": event_locale,
                            }
                        )
                    elif event.type == "turn.failed":
                        code = str(event.payload.get("code") or "llm_unavailable")
                        message = (
                            "回答生成等待过久，请再试一次"
                            if code == "llm_first_token_timeout"
                            else "回答服务暂时不可用，请再试一次"
                        )
                        await send(
                            {
                                "type": "error",
                                "turn_id": turn_id,
                                "code": code,
                                "message": message,
                            }
                        )
                    elif event.type == "turn.cancelled":
                        await send(
                            {
                                "type": "assistant.cancelled",
                                "session_id": event.session_id,
                                "turn_id": event.turn_id,
                                "reason": str(event.payload.get("reason") or "cancelled"),
                            }
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception(
                    "voice.answer.failed connection=%s turn=%s",
                    connection_id,
                    turn_id,
                )
                await send(
                    {"type": "error", "turn_id": turn_id, "message": "回答服务暂时不可用"}
                )
            finally:
                current_task = asyncio.current_task()
                if active_turn_id == turn_id:
                    active_turn_id = None
                    if answer_task is current_task:
                        answer_task = None

        async def start_answer(
            question: str,
            reason: str,
            locale_hint: str = "",
        ) -> None:
            nonlocal answer_task, active_turn_id
            await stop_answer(reason)
            turn_id = uuid.uuid4().hex
            active_turn_id = turn_id
            answer_task = asyncio.create_task(answer(question, turn_id, locale_hint))

        async def commit_voice_batch(generation: int) -> None:
            nonlocal partial_revision
            if generation != batch_generation:
                return
            async with batch_lock:
                if (
                    generation != batch_generation
                    or asr_stream is not None
                    or batch_pending
                    or not batch_results
                ):
                    return
                results = dict(batch_results)
                batch_results.clear()
                ordered_ids = sorted(results)
                failures = {item_id for item_id in ordered_ids if item_id in batch_failures}
                batch_failures.difference_update(ordered_ids)
                asr_candidates = tuple(
                    candidate
                    for item_id in ordered_ids
                    for candidate in batch_candidates.pop(item_id, ())
                    if candidate
                )
                provider_languages = [batch_languages.pop(item_id, "") for item_id in ordered_ids]
                raw_text = " ".join(
                    results[item_id].strip() for item_id in ordered_ids if results[item_id].strip()
                )
                committed_id = ordered_ids[-1]
                if not raw_text:
                    batch_partials.clear()
                    partial_revision = 0
                    if failures:
                        await send(
                            {
                                "type": "error",
                                "utterance_id": committed_id,
                                "code": "asr_unavailable",
                                "message": "语音识别暂时不可用",
                            }
                        )
                    else:
                        await send(
                            {"type": "utterance.rejected", "utterance_id": committed_id}
                        )
                    return
                provider_locale = next(
                    (
                        locale
                        for language in reversed(provider_languages)
                        if (locale := locale_from_provider_language(language))
                    ),
                    None,
                )
                resolved_locale = detect_locale(raw_text, hint=provider_locale or voice_locale_hint)
                normalized = (
                    normalize_asr_final(
                        raw_text,
                        kb=knowledge_base,
                        category=voice_category,
                        recent_items=recent_voice_items(),
                        asr_candidates=asr_candidates,
                    )
                    if is_chinese_locale(resolved_locale)
                    else NormalizedTranscript(raw_text, raw_text, ())
                )
                canonical_text = normalized.canonical_text
                normalizations = [asdict(span) for span in normalized.spans]
                LOGGER.info(
                    "voice.asr.batch_complete connection=%s utterances=%s raw_chars=%s canonical_chars=%s replacements=%s",
                    connection_id,
                    ",".join(str(item_id) for item_id in ordered_ids),
                    len(raw_text),
                    len(canonical_text),
                    len(normalizations),
                )
                await stop_answer("asr_batch")
                await send(
                    {
                        "type": "user.transcript",
                        "utterance_id": committed_id,
                        "revision": partial_revision,
                        "final": True,
                        "text": canonical_text,
                        "raw_text": raw_text,
                        "normalizations": normalizations,
                        "locale": resolved_locale,
                        "asr_engine": "chinese",
                    }
                )
                batch_partials.clear()
                partial_revision = 0
                await start_answer(canonical_text, "new_utterance", resolved_locale)

        async def finish_utterance(
            stream: Any,
            start_task: asyncio.Task[None],
            utterance_id: int,
            generation: int,
        ) -> None:
            try:
                await send(
                    {
                        "type": "status",
                        "status": "transcribing",
                        "utterance_id": utterance_id,
                    }
                )
                await start_task
                transcript = await stream.finish()
                LOGGER.info(
                    "voice.asr.finished connection=%s utterance=%s chars=%s",
                    connection_id,
                    utterance_id,
                    len(transcript),
                )
                if transcript:
                    LOGGER.info(
                        "voice.asr.complete connection=%s utterance=%s chars=%s",
                        connection_id,
                        utterance_id,
                        len(transcript),
                    )
                if generation == batch_generation:
                    batch_results[utterance_id] = transcript
                    batch_candidates[utterance_id] = stream.candidates
                    batch_languages[utterance_id] = stream.detected_language
                    batch_partials[utterance_id] = transcript
            except asyncio.CancelledError:
                raise
            except VoiceProviderError:
                LOGGER.warning(
                    "voice.asr.failed connection=%s utterance=%s",
                    connection_id,
                    utterance_id,
                    exc_info=True,
                )
                if generation == batch_generation:
                    batch_results[utterance_id] = ""
                    batch_candidates[utterance_id] = ()
                    batch_languages[utterance_id] = ""
                    batch_failures.add(utterance_id)
            finally:
                await stream.close()
                pending_user_speaking.discard(utterance_id)
                batch_pending.discard(utterance_id)
                await commit_voice_batch(generation)

        async def start_asr(stream: Any, utterance_id: int) -> None:
            started_at = time.perf_counter()
            LOGGER.info(
                "voice.asr.connect.start connection=%s utterance=%s",
                connection_id,
                utterance_id,
            )
            await stream.start()
            LOGGER.info(
                "voice.asr.connect.ready connection=%s utterance=%s +%.3fs",
                connection_id,
                utterance_id,
                time.perf_counter() - started_at,
            )

        def schedule_finalize(
            stream: Any,
            start_task: asyncio.Task[None],
            utterance_id: int,
        ) -> None:
            batch_pending.add(utterance_id)
            task = asyncio.create_task(
                finish_utterance(stream, start_task, utterance_id, batch_generation)
            )
            finalize_tasks.add(task)

            def clear_finalize(done_task: asyncio.Task[None]) -> None:
                finalize_tasks.discard(done_task)

            task.add_done_callback(clear_finalize)

        try:
            await send({"type": "ready"})
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is not None:
                    if asr_stream is not None:
                        await asr_stream.send_audio(data)
                    continue
                raw = message.get("text")
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "utterance.start":
                    async with batch_lock:
                        utterance_sequence += 1
                        utterance_id = utterance_sequence
                        batch_partials[utterance_id] = ""
                        LOGGER.info(
                            "voice.vad.utterance_start connection=%s utterance=%s interrupt=%s level=%s threshold=%s",
                            connection_id,
                            utterance_id,
                            bool(event.get("interrupt")),
                            event.get("level", "-"),
                            event.get("threshold", "-"),
                        )
                        if asr_stream is not None:
                            previous_stream, asr_stream = asr_stream, None
                            previous_start, asr_start_task = asr_start_task, None
                            previous_id = utterance_id - 1
                            LOGGER.info(
                                "voice.vad.utterance_implicit_end connection=%s utterance=%s",
                                connection_id,
                                previous_id,
                            )
                            if previous_start is not None:
                                schedule_finalize(previous_stream, previous_start, previous_id)
                            else:
                                await previous_stream.close()

                        partial_logged = False

                        async def send_partial(text: str, current: int = utterance_id) -> None:
                            nonlocal partial_logged
                            if current not in batch_partials:
                                return
                            if current in pending_user_speaking and contains_spoken_text(text):
                                await send(
                                    {
                                        "type": "status",
                                        "status": "user_speaking",
                                        "utterance_id": current,
                                    }
                                )
                                pending_user_speaking.discard(current)
                            if not partial_logged:
                                LOGGER.info(
                                    "voice.asr.first_partial connection=%s utterance=%s chars=%s",
                                    connection_id,
                                    current,
                                    len(str(text or "")),
                                )
                                partial_logged = True
                            await send_batch_partial(current, text)

                        if event.get("interrupt"):
                            pending_user_speaking.add(utterance_id)
                        else:
                            pending_user_speaking.discard(utterance_id)
                        asr_stream = make_asr_stream(send_partial)
                        asr_start_task = asyncio.create_task(start_asr(asr_stream, utterance_id))
                        if utterance_id not in pending_user_speaking:
                            await send(
                                {
                                    "type": "status",
                                    "status": "user_speaking",
                                    "utterance_id": utterance_id,
                                }
                            )
                elif event_type == "utterance.end" and asr_stream is not None:
                    async with batch_lock:
                        utterance_id = utterance_sequence
                        LOGGER.info(
                            "voice.vad.utterance_end connection=%s utterance=%s",
                            connection_id,
                            utterance_id,
                        )
                        completed_stream, asr_stream = asr_stream, None
                        completed_start, asr_start_task = asr_start_task, None
                        if completed_start is not None:
                            schedule_finalize(completed_stream, completed_start, utterance_id)
                        else:
                            await completed_stream.close()
                elif event_type == "utterance.cancel":
                    async with batch_lock:
                        clear_voice_batch()
                        await stop_finalize_tasks()
                        await close_active_asr()
                        await send(
                            {"type": "utterance.rejected", "utterance_id": utterance_sequence}
                        )
                elif event_type == "barge_in":
                    async with batch_lock:
                        LOGGER.info(
                            "voice.barge_in connection=%s utterance=%s",
                            connection_id,
                            utterance_sequence,
                        )
                        await stop_answer("barge_in")
                    await send(
                        {
                            "type": "status",
                            "status": "user_speaking",
                            "utterance_id": utterance_sequence,
                        }
                    )
                elif event_type == "text":
                    text = str(event.get("text") or "").strip()
                    if text:
                        async with batch_lock:
                            clear_voice_batch()
                            await stop_finalize_tasks()
                            await close_active_asr()
                            await start_answer(text, "text_input")
                elif event_type == "context":
                    update_voice_context(event)
                elif event_type == "interrupt":
                    async with batch_lock:
                        await stop_answer("client_interrupt")
                        clear_voice_batch()
                        await stop_finalize_tasks()
                        await close_active_asr()
                        await send(
                            {
                                "type": "status",
                                "status": "listening",
                                "utterance_id": utterance_sequence,
                            }
                        )
        except WebSocketDisconnect:
            pass
        finally:
            clear_voice_batch()
            await stop_finalize_tasks()
            await stop_answer("connection_closed")
            await close_active_asr()


__all__ = [
    "MAX_VOICE_CONTEXT_TITLES",
    "MAX_VOICE_RECENT_ITEMS",
    "contains_spoken_text",
    "register_voice_route",
]

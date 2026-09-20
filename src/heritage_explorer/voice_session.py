"""Connection-scoped runtime for realtime browser voice sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
import logging
import time
import uuid
from typing import Any

from .assistant import AssistantService
from .asr_normalization import NormalizedTranscript
from .dataset import KnowledgeBase
from .language import (
    detect_locale,
    is_chinese_locale,
    locale_from_provider_language,
    normalize_locale_hint,
)
from .sessions import SessionStore
from .voice import VoiceProviderError
from .voice_events import (
    AssistantCancelledEvent,
    AssistantDeltaEvent,
    AssistantDoneEvent,
    SourcesEvent,
    UserPartialEvent,
    UserTranscriptEvent,
    UtteranceRejectedEvent,
    VoiceErrorEvent,
    VoiceServerEvent,
    VoiceStatusEvent,
)
from .voice_lifecycle import VoiceConnectionScope
from .voice_protocol import (
    BargeInCommand,
    ContextCommand,
    InterruptCommand,
    TextCommand,
    UtteranceCancelCommand,
    UtteranceEndCommand,
    UtteranceStartCommand,
    VoiceCommand,
)


MAX_VOICE_CONTEXT_TITLES = 8
MAX_VOICE_RECENT_ITEMS = 8
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def contains_spoken_text(value: object) -> bool:
    """Punctuation-only ASR hypotheses are not evidence of human speech."""

    return any(character.isalnum() for character in str(value or ""))


@dataclass(slots=True)
class VoiceContextState:
    """Canonical conversation context for one realtime voice connection."""

    session_id: str | None = None
    category: str = ""
    titles: list[str] = field(default_factory=list)
    locale_hint: str = ""

    def apply(self, command: ContextCommand, *, max_session_id_chars: int) -> None:
        self.category = command.category[:200]
        if command.session_id:
            self.session_id = command.session_id[:max_session_id_chars]

        incoming_locale = normalize_locale_hint(command.locale_hint)
        if incoming_locale:
            self.locale_hint = incoming_locale

        titles: list[str] = []
        seen: set[str] = set()
        for value in (command.selected_title, *command.titles):
            title = str(value or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            titles.append(title[:200])
            if len(titles) >= MAX_VOICE_CONTEXT_TITLES:
                break
        self.titles = titles


@dataclass(slots=True)
class VoiceBatchState:
    """Mutable ASR batch state owned by exactly one connection runtime."""

    results: dict[int, str] = field(default_factory=dict)
    candidates: dict[int, tuple[str, ...]] = field(default_factory=dict)
    languages: dict[int, str] = field(default_factory=dict)
    failures: set[int] = field(default_factory=set)
    partials: dict[int, str] = field(default_factory=dict)
    pending_user_speaking: set[int] = field(default_factory=set)
    pending: set[int] = field(default_factory=set)
    revision: int = 0
    generation: int = 0

    def clear(self) -> None:
        self.generation += 1
        self.results.clear()
        self.candidates.clear()
        self.languages.clear()
        self.failures.clear()
        self.partials.clear()
        self.pending_user_speaking.clear()
        self.pending.clear()
        self.revision = 0

    def combined_partial_text(self) -> str:
        return " ".join(
            self.partials[item_id].strip()
            for item_id in sorted(self.partials)
            if self.partials[item_id].strip()
        ).strip()


class VoiceSessionRuntime:
    """Own mutable conversation state for one voice connection."""

    def __init__(
        self,
        *,
        emit: Callable[[VoiceServerEvent], Awaitable[None]],
        connection_id: str,
        assistant: AssistantService,
        sessions: SessionStore,
        knowledge_base: KnowledgeBase,
        app_id: str,
        api_key: str,
        api_secret: str,
        asr_host: str,
        stream_factory: Callable[..., Any],
        normalize_final: Callable[..., NormalizedTranscript],
        max_session_id_chars: int,
    ) -> None:
        self.emit = emit
        self.connection_id = connection_id
        self.assistant = assistant
        self.sessions = sessions
        self.knowledge_base = knowledge_base
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.asr_host = asr_host
        self.stream_factory = stream_factory
        self.normalize_final = normalize_final
        self.max_session_id_chars = max_session_id_chars

        self.context = VoiceContextState()
        self.batch = VoiceBatchState()
        self.lifecycle = VoiceConnectionScope()
        self.utterance_sequence = 0
        self.batch_lock = asyncio.Lock()

    def update_context(self, command: ContextCommand) -> None:
        self.context.apply(
            command,
            max_session_id_chars=self.max_session_id_chars,
        )

    def recent_voice_items(self) -> tuple[Any, ...]:
        if not self.context.session_id:
            return ()
        recent: list[Any] = []
        seen: set[str] = set()
        for turn in reversed(self.sessions.history(self.context.session_id)):
            for source_id in reversed(turn.source_ids):
                if source_id in seen:
                    continue
                item = self.knowledge_base.get(source_id)
                if item is not None:
                    seen.add(source_id)
                    recent.append(item)
                if len(recent) >= MAX_VOICE_RECENT_ITEMS:
                    return tuple(recent)
        return tuple(recent)

    def make_asr_stream(self, on_partial: Any) -> Any:
        recent = self.recent_voice_items()
        recent_titles = [str(getattr(item, "title", "") or "") for item in recent]
        hotwords: list[str] = []
        seen: set[str] = set()
        for title in [self.context.category, *self.context.titles, *recent_titles]:
            title = title.strip()
            if title and title not in seen:
                seen.add(title)
                hotwords.append(title)
            if len(hotwords) >= MAX_VOICE_CONTEXT_TITLES + MAX_VOICE_RECENT_ITEMS:
                break
        return self.stream_factory(
            app_id=self.app_id,
            api_key=self.api_key,
            api_secret=self.api_secret,
            host=self.asr_host,
            language="zh_cn",
            accent="mandarin",
            domain="slm",
            dynamic_correction=True,
            on_partial=on_partial,
            hotwords=tuple(hotwords),
        )

    async def send(self, event: VoiceServerEvent) -> None:
        await self.emit(event)

    def log_answer_cancel(self, reason: str) -> None:
        task = self.lifecycle.answer_task
        turn_id = self.lifecycle.active_turn_id
        if task is not None and not task.done():
            LOGGER.info(
                "voice.answer.cancel connection=%s turn=%s reason=%s",
                self.connection_id,
                turn_id or "-",
                reason,
            )

    async def send_batch_partial(self, utterance_id: int, text: str) -> None:
        if utterance_id not in self.batch.partials:
            return
        self.batch.partials[utterance_id] = str(text or "")
        combined = self.batch.combined_partial_text()
        if not combined:
            return
        self.batch.revision += 1
        await self.send(
            UserPartialEvent(
                utterance_id=max(self.batch.partials),
                revision=self.batch.revision,
                text=combined,
            )
        )

    async def stop_answer(self, reason: str) -> None:
        self.log_answer_cancel(reason)
        await self.lifecycle.cancel_answer()

    async def answer(self, question: str, turn_id: str, locale_hint: str = "") -> None:
        answer_locale = detect_locale(
            question,
            hint=locale_hint or self.context.locale_hint,
        )
        LOGGER.info(
            "voice.agent.thinking connection=%s turn=%s question_chars=%s",
            self.connection_id,
            turn_id,
            len(question),
        )
        await self.send(
            VoiceStatusEvent(
                "thinking",
                turn_id=turn_id,
                locale=answer_locale,
            )
        )
        try:
            async for event in self.assistant.stream_turn(
                question,
                session_id=self.context.session_id,
                turn_id=turn_id,
                category=self.context.category,
                locale_hint=answer_locale,
            ):
                if self.lifecycle.active_turn_id != turn_id:
                    return
                self.context.session_id = event.session_id
                if event.type == "response.text.delta":
                    event_locale = str(event.payload.get("locale") or answer_locale)
                    await self.send(
                        AssistantDeltaEvent(
                            session_id=event.session_id,
                            turn_id=event.turn_id,
                            text=str(event.payload.get("delta") or ""),
                            locale=event_locale,
                        )
                    )
                elif event.type == "response.sources":
                    sources = tuple(
                        dict(item)
                        for item in event.payload.get("sources", [])
                        if isinstance(item, dict)
                    )
                    await self.send(
                        SourcesEvent(
                            session_id=event.session_id,
                            turn_id=event.turn_id,
                            items=sources,
                        )
                    )
                elif event.type == "turn.completed":
                    event_locale = str(event.payload.get("locale") or answer_locale)
                    await self.send(
                        AssistantDoneEvent(
                            session_id=event.session_id,
                            turn_id=event.turn_id,
                            text=str(event.payload.get("answer") or ""),
                            locale=event_locale,
                        )
                    )
                elif event.type == "turn.failed":
                    code = str(event.payload.get("code") or "llm_unavailable")
                    message = (
                        "回答生成等待过久，请再试一次"
                        if code == "llm_first_token_timeout"
                        else "回答服务暂时不可用，请再试一次"
                    )
                    await self.send(
                        VoiceErrorEvent(
                            message,
                            code=code,
                            turn_id=turn_id,
                        )
                    )
                elif event.type == "turn.cancelled":
                    await self.send(
                        AssistantCancelledEvent(
                            session_id=event.session_id,
                            turn_id=event.turn_id,
                            reason=str(event.payload.get("reason") or "cancelled"),
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "voice.answer.failed connection=%s turn=%s",
                self.connection_id,
                turn_id,
            )
            await self.send(
                VoiceErrorEvent(
                    "回答服务暂时不可用",
                    turn_id=turn_id,
                )
            )
        finally:
            self.lifecycle.clear_answer_if(asyncio.current_task(), turn_id)

    async def start_answer(
        self,
        question: str,
        reason: str,
        locale_hint: str = "",
    ) -> None:
        await self.stop_answer(reason)
        turn_id = uuid.uuid4().hex
        self.lifecycle.start_answer(
            turn_id,
            self.answer(question, turn_id, locale_hint),
            name=f"voice-answer-{turn_id}",
        )

    async def commit_voice_batch(self, generation: int) -> None:
        if generation != self.batch.generation:
            return
        async with self.batch_lock:
            if (
                generation != self.batch.generation
                or self.lifecycle.asr_stream is not None
                or self.batch.pending
                or not self.batch.results
            ):
                return

            results = dict(self.batch.results)
            self.batch.results.clear()
            ordered_ids = sorted(results)
            failures = {
                item_id
                for item_id in ordered_ids
                if item_id in self.batch.failures
            }
            self.batch.failures.difference_update(ordered_ids)
            asr_candidates = tuple(
                candidate
                for item_id in ordered_ids
                for candidate in self.batch.candidates.pop(item_id, ())
                if candidate
            )
            provider_languages = [
                self.batch.languages.pop(item_id, "")
                for item_id in ordered_ids
            ]
            raw_text = " ".join(
                results[item_id].strip()
                for item_id in ordered_ids
                if results[item_id].strip()
            )
            committed_id = ordered_ids[-1]

            if not raw_text:
                self.batch.partials.clear()
                self.batch.revision = 0
                if failures:
                    await self.send(
                        VoiceErrorEvent(
                            "语音识别暂时不可用",
                            code="asr_unavailable",
                            utterance_id=committed_id,
                        )
                    )
                else:
                    await self.send(UtteranceRejectedEvent(committed_id))
                return

            provider_locale = next(
                (
                    locale
                    for language in reversed(provider_languages)
                    if (locale := locale_from_provider_language(language))
                ),
                None,
            )
            resolved_locale = detect_locale(
                raw_text,
                hint=provider_locale or self.context.locale_hint,
            )
            normalized = (
                self.normalize_final(
                    raw_text,
                    kb=self.knowledge_base,
                    category=self.context.category,
                    recent_items=self.recent_voice_items(),
                    asr_candidates=asr_candidates,
                )
                if is_chinese_locale(resolved_locale)
                else NormalizedTranscript(raw_text, raw_text, ())
            )
            canonical_text = normalized.canonical_text
            normalizations = tuple(asdict(span) for span in normalized.spans)
            LOGGER.info(
                "voice.asr.batch_complete connection=%s utterances=%s raw_chars=%s canonical_chars=%s replacements=%s",
                self.connection_id,
                ",".join(str(item_id) for item_id in ordered_ids),
                len(raw_text),
                len(canonical_text),
                len(normalizations),
            )
            await self.stop_answer("asr_batch")
            await self.send(
                UserTranscriptEvent(
                    utterance_id=committed_id,
                    revision=self.batch.revision,
                    text=canonical_text,
                    raw_text=raw_text,
                    normalizations=normalizations,
                    locale=resolved_locale,
                    asr_engine="chinese",
                )
            )
            self.batch.partials.clear()
            self.batch.revision = 0
            await self.start_answer(
                canonical_text,
                "new_utterance",
                resolved_locale,
            )

    async def finish_utterance(
        self,
        stream: Any,
        start_task: asyncio.Task[None],
        utterance_id: int,
        generation: int,
    ) -> None:
        try:
            await self.send(
                VoiceStatusEvent(
                    "transcribing",
                    utterance_id=utterance_id,
                )
            )
            await start_task
            transcript = await stream.finish()
            LOGGER.info(
                "voice.asr.finished connection=%s utterance=%s chars=%s",
                self.connection_id,
                utterance_id,
                len(transcript),
            )
            if transcript:
                LOGGER.info(
                    "voice.asr.complete connection=%s utterance=%s chars=%s",
                    self.connection_id,
                    utterance_id,
                    len(transcript),
                )
            if generation == self.batch.generation:
                self.batch.results[utterance_id] = transcript
                self.batch.candidates[utterance_id] = stream.candidates
                self.batch.languages[utterance_id] = stream.detected_language
                self.batch.partials[utterance_id] = transcript
        except asyncio.CancelledError:
            raise
        except VoiceProviderError:
            LOGGER.warning(
                "voice.asr.failed connection=%s utterance=%s",
                self.connection_id,
                utterance_id,
                exc_info=True,
            )
            if generation == self.batch.generation:
                self.batch.results[utterance_id] = ""
                self.batch.candidates[utterance_id] = ()
                self.batch.languages[utterance_id] = ""
                self.batch.failures.add(utterance_id)
        finally:
            await stream.close()
            self.batch.pending_user_speaking.discard(utterance_id)
            self.batch.pending.discard(utterance_id)
            await self.commit_voice_batch(generation)

    async def start_asr(self, stream: Any, utterance_id: int) -> None:
        started_at = time.perf_counter()
        LOGGER.info(
            "voice.asr.connect.start connection=%s utterance=%s",
            self.connection_id,
            utterance_id,
        )
        await stream.start()
        LOGGER.info(
            "voice.asr.connect.ready connection=%s utterance=%s +%.3fs",
            self.connection_id,
            utterance_id,
            time.perf_counter() - started_at,
        )

    def schedule_finalize(
        self,
        stream: Any,
        start_task: asyncio.Task[None],
        utterance_id: int,
    ) -> None:
        self.batch.pending.add(utterance_id)
        self.lifecycle.start_finalizer(
            self.finish_utterance(
                stream,
                start_task,
                utterance_id,
                self.batch.generation,
            ),
            name=f"voice-finalize-{utterance_id}",
        )

    async def handle_audio(self, data: bytes) -> None:
        stream = self.lifecycle.asr_stream
        if stream is not None:
            await stream.send_audio(data)

    async def handle_utterance_start(
        self,
        command: UtteranceStartCommand,
    ) -> None:
        async with self.batch_lock:
            self.utterance_sequence += 1
            utterance_id = self.utterance_sequence
            self.batch.partials[utterance_id] = ""
            LOGGER.info(
                "voice.vad.utterance_start connection=%s utterance=%s interrupt=%s level=%s threshold=%s",
                self.connection_id,
                utterance_id,
                command.interrupt,
                command.level if command.level is not None else "-",
                command.threshold if command.threshold is not None else "-",
            )

            if self.lifecycle.asr_stream is not None:
                previous_stream, previous_start = self.lifecycle.detach_asr()
                previous_id = utterance_id - 1
                LOGGER.info(
                    "voice.vad.utterance_implicit_end connection=%s utterance=%s",
                    self.connection_id,
                    previous_id,
                )
                if previous_start is not None:
                    self.schedule_finalize(
                        previous_stream,
                        previous_start,
                        previous_id,
                    )
                elif previous_stream is not None:
                    await previous_stream.close()

            partial_logged = False

            async def send_partial(text: str, current: int = utterance_id) -> None:
                nonlocal partial_logged
                if current not in self.batch.partials:
                    return
                if (
                    current in self.batch.pending_user_speaking
                    and contains_spoken_text(text)
                ):
                    await self.send(
                        VoiceStatusEvent(
                            "user_speaking",
                            utterance_id=current,
                        )
                    )
                    self.batch.pending_user_speaking.discard(current)
                if not partial_logged:
                    LOGGER.info(
                        "voice.asr.first_partial connection=%s utterance=%s chars=%s",
                        self.connection_id,
                        current,
                        len(str(text or "")),
                    )
                    partial_logged = True
                await self.send_batch_partial(current, text)

            if command.interrupt:
                self.batch.pending_user_speaking.add(utterance_id)
            else:
                self.batch.pending_user_speaking.discard(utterance_id)

            stream = self.make_asr_stream(send_partial)
            self.lifecycle.start_asr(
                stream,
                self.start_asr(stream, utterance_id),
                name=f"voice-asr-start-{utterance_id}",
            )
            if utterance_id not in self.batch.pending_user_speaking:
                await self.send(
                    VoiceStatusEvent(
                        "user_speaking",
                        utterance_id=utterance_id,
                    )
                )

    async def handle_utterance_end(self) -> None:
        if self.lifecycle.asr_stream is None:
            return
        async with self.batch_lock:
            utterance_id = self.utterance_sequence
            LOGGER.info(
                "voice.vad.utterance_end connection=%s utterance=%s",
                self.connection_id,
                utterance_id,
            )
            completed_stream, completed_start = self.lifecycle.detach_asr()
            if completed_stream is None:
                return
            if completed_start is not None:
                self.schedule_finalize(
                    completed_stream,
                    completed_start,
                    utterance_id,
                )
            else:
                await completed_stream.close()

    async def handle_utterance_cancel(self) -> None:
        async with self.batch_lock:
            self.batch.clear()
            await self.lifecycle.cancel_finalizers()
            await self.lifecycle.cancel_asr()
            await self.send(UtteranceRejectedEvent(self.utterance_sequence))

    async def handle_barge_in(self) -> None:
        async with self.batch_lock:
            LOGGER.info(
                "voice.barge_in connection=%s utterance=%s",
                self.connection_id,
                self.utterance_sequence,
            )
            await self.stop_answer("barge_in")
        await self.send(
            VoiceStatusEvent(
                "user_speaking",
                utterance_id=self.utterance_sequence,
            )
        )

    async def handle_text(self, command: TextCommand) -> None:
        if not command.text:
            return
        async with self.batch_lock:
            self.batch.clear()
            await self.lifecycle.cancel_finalizers()
            await self.lifecycle.cancel_asr()
            await self.start_answer(command.text, "text_input")

    def handle_context(self, command: ContextCommand) -> None:
        self.update_context(command)

    async def handle_interrupt(self) -> None:
        async with self.batch_lock:
            await self.stop_answer("client_interrupt")
            self.batch.clear()
            await self.lifecycle.cancel_finalizers()
            await self.lifecycle.cancel_asr()
            await self.send(
                VoiceStatusEvent(
                    "listening",
                    utterance_id=self.utterance_sequence,
                )
            )

    async def handle_command(self, command: VoiceCommand) -> None:
        if isinstance(command, UtteranceStartCommand):
            await self.handle_utterance_start(command)
        elif isinstance(command, UtteranceEndCommand):
            await self.handle_utterance_end()
        elif isinstance(command, UtteranceCancelCommand):
            await self.handle_utterance_cancel()
        elif isinstance(command, BargeInCommand):
            await self.handle_barge_in()
        elif isinstance(command, TextCommand):
            await self.handle_text(command)
        elif isinstance(command, ContextCommand):
            self.handle_context(command)
        elif isinstance(command, InterruptCommand):
            await self.handle_interrupt()

    async def close(self) -> None:
        self.batch.clear()
        self.log_answer_cancel("connection_closed")
        await self.lifecycle.close()


__all__ = [
    "MAX_VOICE_CONTEXT_TITLES",
    "MAX_VOICE_RECENT_ITEMS",
    "VoiceBatchState",
    "VoiceContextState",
    "VoiceSessionRuntime",
    "contains_spoken_text",
]

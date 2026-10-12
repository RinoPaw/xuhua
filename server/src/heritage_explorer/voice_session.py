"""Connection-scoped runtime for realtime browser voice sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
import logging
import time
import uuid
from typing import Any

from .admission import AdmissionController, AdmissionDenied, AdmissionLease
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
from .voice_events import (
    AssistantCancelledEvent,
    AssistantDeltaEvent,
    AssistantDoneEvent,
    InterruptAckEvent,
    SourcesEvent,
    UserPartialEvent,
    UserTranscriptEvent,
    UtteranceRejectedEvent,
    VoiceErrorEvent,
    VoiceServerEvent,
    VoiceStatusEvent,
)
from .voice_lifecycle import VoiceConnectionScope, close_resource
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
ASSISTANT_NAME = "叙华"
ASSISTANT_ACKNOWLEDGEMENT = "我在。"
_ASSISTANT_ADDRESS_TRIM = " \t\r\n，,。！？!?：:、~～"
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def contains_spoken_text(value: object) -> bool:
    """Punctuation-only ASR hypotheses are not evidence of human speech."""

    return any(character.isalnum() for character in str(value or ""))


def is_assistant_address_only(value: object) -> bool:
    """Return whether one final transcript only calls the assistant by name."""

    return str(value or "").strip(_ASSISTANT_ADDRESS_TRIM) == ASSISTANT_NAME


def build_voice_hotwords(
    category: str,
    titles: list[str] | tuple[str, ...],
    recent_titles: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    """Keep the assistant name in every ASR request before contextual terms."""

    hotwords = [ASSISTANT_NAME]
    seen = {ASSISTANT_NAME}
    limit = 1 + MAX_VOICE_CONTEXT_TITLES + MAX_VOICE_RECENT_ITEMS
    for value in (category, *titles, *recent_titles):
        title = str(value or "").strip()
        if title and title not in seen:
            seen.add(title)
            hotwords.append(title)
        if len(hotwords) >= limit:
            break
    return tuple(hotwords)


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
        admission: AdmissionController,
        client_id: str,
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
        self.admission = admission
        self.client_id = client_id

        self.context = VoiceContextState()
        self.batch = VoiceBatchState()
        self.lifecycle = VoiceConnectionScope(connection_id=connection_id)
        self.utterance_sequence = 0
        # PCM belonging to a capacity-rejected start must not leak into the
        # preceding ASR stream. The flag is cleared by its matching end/cancel.
        self._discarding_utterance = False
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
        hotwords = build_voice_hotwords(
            self.context.category,
            self.context.titles,
            recent_titles,
        )
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
            hotwords=hotwords,
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

    async def acknowledge_address(self, locale_hint: str = "") -> None:
        """Answer a pure name call without retrieval, LLM work, or session history."""

        turn_id = uuid.uuid4().hex
        locale = detect_locale(
            ASSISTANT_ACKNOWLEDGEMENT,
            hint=locale_hint or self.context.locale_hint,
        )
        session_id = self.context.session_id or ""
        LOGGER.info(
            "voice.address.ack connection=%s turn=%s",
            self.connection_id,
            turn_id,
        )
        await self.send(
            AssistantDeltaEvent(
                session_id=session_id,
                turn_id=turn_id,
                text=ASSISTANT_ACKNOWLEDGEMENT,
                locale=locale,
            )
        )
        await self.send(
            AssistantDoneEvent(
                session_id=session_id,
                turn_id=turn_id,
                text=ASSISTANT_ACKNOWLEDGEMENT,
                locale=locale,
            )
        )

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
        started_at = time.perf_counter()
        first_delta_logged = False
        outcome = "interrupted"
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
                    delta = str(event.payload.get("delta") or "")
                    if delta and not first_delta_logged:
                        first_delta_logged = True
                        LOGGER.info(
                            "voice.llm.first_delta connection=%s turn=%s elapsed_ms=%.1f",
                            self.connection_id,
                            turn_id,
                            (time.perf_counter() - started_at) * 1000,
                        )
                    event_locale = str(event.payload.get("locale") or answer_locale)
                    await self.send(
                        AssistantDeltaEvent(
                            session_id=event.session_id,
                            turn_id=turn_id,
                            text=delta,
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
                            turn_id=turn_id,
                            items=sources,
                        )
                    )
                elif event.type == "turn.completed":
                    outcome = "completed"
                    event_locale = str(event.payload.get("locale") or answer_locale)
                    await self.send(
                        AssistantDoneEvent(
                            session_id=event.session_id,
                            turn_id=turn_id,
                            text=str(event.payload.get("answer") or ""),
                            locale=event_locale,
                        )
                    )
                elif event.type == "turn.failed":
                    outcome = "failed"
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
                    outcome = "cancelled"
                    await self.send(
                        AssistantCancelledEvent(
                            session_id=event.session_id,
                            turn_id=turn_id,
                            reason=str(event.payload.get("reason") or "cancelled"),
                        )
                    )
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "failed"
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
            LOGGER.info(
                "voice.llm.finish connection=%s turn=%s outcome=%s "
                "elapsed_ms=%.1f first_delta=%s",
                self.connection_id,
                turn_id,
                outcome,
                (time.perf_counter() - started_at) * 1000,
                first_delta_logged,
            )
            await self.lifecycle.finish_answer(asyncio.current_task(), turn_id)

    async def start_answer(
        self,
        question: str,
        reason: str,
        locale_hint: str = "",
        *,
        requested_turn_id: str = "",
    ) -> None:
        await self.stop_answer(reason)
        try:
            # HTTP /api/chat and voice turns share the same chat capacity and
            # rolling rate buckets. The long-lived voice socket is only a
            # transport lease; it must not permit unlimited assistant turns.
            lease = await self.admission.acquire("chat", self.client_id)
        except AdmissionDenied as exc:
            await self.send(
                VoiceErrorEvent(
                    "回答请求过于频繁，请稍后再试",
                    code=f"chat_{exc.reason}",
                    turn_id=requested_turn_id,
                )
            )
            return

        turn_id = requested_turn_id or uuid.uuid4().hex
        try:
            self.lifecycle.start_answer(
                turn_id,
                self.answer(question, turn_id, locale_hint),
                name=f"voice-answer-{turn_id}",
                lease=lease,
            )
        except BaseException:
            await lease.release()
            raise

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
                # Even empty batches have ended; later ASR callbacks belong to
                # a superseded generation and cannot enter the next question.
                self.batch.clear()
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
            revision = self.batch.revision
            # A completed batch owns exactly one assistant turn. Start the
            # next normal utterance in a fresh generation as well as after
            # explicit cancellations/text inputs.
            self.batch.clear()
            await self.stop_answer("asr_batch")
            await self.send(
                UserTranscriptEvent(
                    utterance_id=committed_id,
                    revision=revision,
                    text=canonical_text,
                    raw_text=raw_text,
                    normalizations=normalizations,
                    locale=resolved_locale,
                    asr_engine="chinese",
                )
            )
            if is_assistant_address_only(canonical_text):
                await self.acknowledge_address(resolved_locale)
                return
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
        final_started_at = time.perf_counter()
        final_status = "cancelled"
        try:
            await self.send(
                VoiceStatusEvent(
                    "transcribing",
                    utterance_id=utterance_id,
                )
            )
            await start_task
            # XfyunStream exposes its final transcript before waiting for
            # websocket teardown. Keep supporting injected/legacy streams
            # whose finish() still combines both operations.
            finish_result = getattr(stream, "finish_result", None)
            transcript = (
                await finish_result()
                if finish_result is not None
                else await stream.finish()
            )
            final_status = "completed"
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
        except Exception:
            # Provider setup/finalization can raise exceptions other than
            # VoiceProviderError (e.g. a failed socket or decoder task).
            # The finalizer must still commit a terminal failure so the
            # browser does not wait for a transcript that will never arrive.
            final_status = "failed"
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
            LOGGER.info(
                "voice.asr.finalize connection=%s utterance=%s status=%s "
                "finalize_ms=%.1f",
                self.connection_id,
                utterance_id,
                final_status,
                (time.perf_counter() - final_started_at) * 1000,
            )
            self.batch.pending_user_speaking.discard(utterance_id)
            self.batch.pending.discard(utterance_id)
            try:
                # A final transcript can enter the answer pipeline immediately.
                # The finalizer still owns the detached provider stream and
                # admission lease until its cleanup finishes; cancellation and
                # connection close continue to join this owned task.
                await self.commit_voice_batch(generation)
            finally:
                await self.lifecycle.release_asr(stream, label="voice.asr.finalizer")

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
        if self._discarding_utterance:
            return
        stream = self.lifecycle.asr_stream
        if stream is not None:
            await stream.send_audio(data)

    async def reject_asr_start(self, reason: str) -> None:
        """Reject only this VAD segment without destroying the voice socket.

        A prior active stream must be detached before rejecting the new one,
        otherwise the rejected segment's PCM could contaminate that stream.
        Previously admitted finalizers and their leases remain owned by the
        connection and continue to completion.
        """
        if self.lifecycle.asr_stream is not None:
            previous_id = self.utterance_sequence
            previous_stream, previous_start = self.lifecycle.detach_asr()
            if previous_start is not None:
                self.schedule_finalize(previous_stream, previous_start, previous_id)
            elif previous_stream is not None:
                await self.lifecycle.release_asr(previous_stream, label="voice.asr.replaced")
        self.utterance_sequence += 1
        self._discarding_utterance = True
        LOGGER.info(
            "voice.asr.admission_rejected connection=%s utterance=%s reason=%s active=%s",
            self.connection_id,
            self.utterance_sequence,
            reason,
            self.lifecycle.active_asr_operations,
        )
        await self.send(UtteranceRejectedEvent(self.utterance_sequence, reason=reason))

    async def handle_utterance_start(
        self,
        command: UtteranceStartCommand,
    ) -> None:
        async with self.batch_lock:
            # A new start supersedes any missing end from an earlier rejected
            # attempt. No provider or lease was allocated to that attempt.
            self._discarding_utterance = False
            if not self.lifecycle.can_start_asr():
                await self.reject_asr_start("voice_asr_capacity")
                return
            try:
                # Budget is acquired before the provider stream is constructed;
                # previous finalizers continue holding their own reservations.
                asr_lease = await self.admission.acquire("asr", self.client_id)
            except AdmissionDenied as exc:
                await self.reject_asr_start(f"voice_asr_{exc.reason}")
                return
            lease_transferred = False
            try:
                emit_speaking_status = await self._begin_utterance(command, asr_lease)
                lease_transferred = True
            finally:
                if not lease_transferred:
                    await asr_lease.release()
            # The new ASR stream already owns the lease before sending status;
            # cancellation of websocket I/O must not release an active lease.
            if emit_speaking_status:
                await self.send(
                    VoiceStatusEvent(
                        "user_speaking",
                        utterance_id=self.utterance_sequence,
                    )
                )

    async def _begin_utterance(
        self,
        command: UtteranceStartCommand,
        asr_lease: AdmissionLease,
    ) -> bool:
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
                await self.lifecycle.release_asr(previous_stream, label="voice.asr.replaced")

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
        try:
            self.lifecycle.start_asr(
                stream,
                self.start_asr(stream, utterance_id),
                name=f"voice-asr-start-{utterance_id}",
                lease=asr_lease,
                utterance_id=utterance_id,
            )
        except BaseException:
            await close_resource(stream, label="voice.asr.unowned")
            raise
        return utterance_id not in self.batch.pending_user_speaking

    async def handle_utterance_end(self) -> None:
        async with self.batch_lock:
            if self._discarding_utterance:
                self._discarding_utterance = False
                return
            if self.lifecycle.asr_stream is None:
                return
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
                await self.lifecycle.release_asr(completed_stream, label="voice.asr.completed")

    async def handle_utterance_cancel(self) -> None:
        async with self.batch_lock:
            if self._discarding_utterance:
                self._discarding_utterance = False
                return
            self.batch.clear()
            await self.lifecycle.cancel_finalizers()
            await self.lifecycle.cancel_asr()
            await self.send(UtteranceRejectedEvent(self.utterance_sequence))

    async def confirm_interruption(
        self, *, request_id: str, reason: str, cancel_asr: bool
    ) -> None:
        """Acknowledge only after the answer (and optional ASR) is cancelled."""

        turn_id = self.lifecycle.active_turn_id or ""
        task = self.lifecycle.answer_task
        cancelled = task is not None and not task.done()
        await self.stop_answer(reason)
        if cancel_asr:
            self.batch.clear()
            await self.lifecycle.cancel_finalizers()
            await self.lifecycle.cancel_asr()
        await self.send(
            InterruptAckEvent(
                request_id=request_id,
                reason=reason,
                turn_id=turn_id,
                utterance_id=self.utterance_sequence,
                cancelled=cancelled,
            )
        )
        LOGGER.info(
            "voice.interrupt.ack connection=%s request=%s reason=%s "
            "turn=%s utterance=%s cancelled=%s",
            self.connection_id, request_id or "-", reason, turn_id or "-",
            self.utterance_sequence, cancelled,
        )

    async def handle_barge_in(self, command: BargeInCommand) -> None:
        async with self.batch_lock:
            if self._discarding_utterance:
                return
            LOGGER.info(
                "voice.barge_in connection=%s utterance=%s",
                self.connection_id,
                self.utterance_sequence,
            )
            # Preserve the new ASR stream while cancelling only the old answer.
            await self.confirm_interruption(
                request_id=command.request_id, reason="barge_in", cancel_asr=False
            )
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
            await self.start_answer(
                command.text, "text_input", requested_turn_id=command.turn_id
            )

    def handle_context(self, command: ContextCommand) -> None:
        self.update_context(command)

    async def handle_interrupt(self, command: InterruptCommand) -> None:
        async with self.batch_lock:
            await self.confirm_interruption(
                request_id=command.request_id, reason="client_interrupt",
                cancel_asr=True,
            )
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
            await self.handle_barge_in(command)
        elif isinstance(command, TextCommand):
            await self.handle_text(command)
        elif isinstance(command, ContextCommand):
            self.handle_context(command)
        elif isinstance(command, InterruptCommand):
            await self.handle_interrupt(command)

    async def close(self) -> None:
        self._discarding_utterance = False
        self.batch.clear()
        self.log_answer_cancel("connection_closed")
        await self.lifecycle.close()


__all__ = [
    "ASSISTANT_ACKNOWLEDGEMENT",
    "ASSISTANT_NAME",
    "MAX_VOICE_CONTEXT_TITLES",
    "MAX_VOICE_RECENT_ITEMS",
    "VoiceBatchState",
    "VoiceContextState",
    "VoiceSessionRuntime",
    "build_voice_hotwords",
    "contains_spoken_text",
    "is_assistant_address_only",
]

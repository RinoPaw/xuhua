"""The answer pipeline shared by text and voice transports."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Sequence

from .answer_policy import (
    confidence,
    fallback_answer,
    is_greeting,
    localized_copy,
    localized_greeting_suggestions,
    short_reply_mode,
    suggestions,
    used_sources,
)
from .config import (
    AI_API_KEY,
    AI_BASE_URL,
    AI_FIRST_TOKEN_MAX_ATTEMPTS,
    AI_FIRST_TOKEN_TIMEOUT,
    AI_MAX_CONTEXT_CHARS,
    AI_MODEL,
    AI_TIMEOUT,
)
from .dataset import HeritageItem, KnowledgeBase, get_knowledge_base, item_to_dict, normalize_text
from .events import EventSequence
from .language import DEFAULT_LOCALE, detect_locale
from .llm_stream import LLMEmptyStream, LLMFirstTokenTimeout, stream_with_first_token_retry
from .models import AssistantEvent, ConversationTurn, SearchResponse
from .prompting import build_messages
from .providers.llm import LLMProvider, OpenAICompatibleLLM
from .retrieval_policy import (
    candidate_limit,
    exploration_offset,
    is_scope_browse,
    localized_search_query,
    retrieval_basis,
)
from .search import search_items
from .sessions import SessionStore


MAX_QUESTION_CHARS = 4000
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


class SearchService:
    """One stable search entry point for APIs, chat and voice."""

    def __init__(self, knowledge_base: KnowledgeBase | None = None) -> None:
        self.knowledge_base = knowledge_base or get_knowledge_base()

    def search(
        self,
        query: str = "",
        *,
        category: str = "",
        province: str = "",
        level: str = "",
        district: str = "",
        keywords: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> SearchResponse:
        safe_limit = min(max(int(limit), 1), 100)
        safe_offset = max(int(offset), 0)
        items, total = search_items(
            self.knowledge_base,
            query=normalize_text(query),
            category=normalize_text(category),
            province=normalize_text(province),
            level=normalize_text(level),
            district=normalize_text(district),
            keywords=normalize_text(keywords),
            limit=safe_limit,
            offset=safe_offset,
            use_pinyin=True,
        )
        return SearchResponse(items=tuple(items), total=total)


class AssistantService:
    """Coordinate one conversational turn without owning policy internals."""

    def __init__(
        self,
        *,
        search: SearchService | None = None,
        sessions: SessionStore | None = None,
        llm: LLMProvider | None = None,
        max_candidates: int = 12,
    ) -> None:
        self.search = search or SearchService()
        self.sessions = sessions or SessionStore()
        self.llm = llm or OpenAICompatibleLLM(
            api_key=AI_API_KEY,
            base_url=AI_BASE_URL,
            model=AI_MODEL,
            timeout=AI_TIMEOUT,
        )
        self.max_candidates = max(1, min(max_candidates, 20))

    async def aclose(self) -> None:
        close = getattr(self.llm, "aclose", None)
        if close is not None:
            await close()

    async def stream_turn(
        self,
        question: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        category: str = "",
        locale_hint: str = "",
    ) -> AsyncIterator[AssistantEvent]:
        question = normalize_text(str(question or ""))
        locale = detect_locale(question, hint=locale_hint)
        if not question:
            session = self.sessions.get_or_create(session_id)
            turn = turn_id or uuid.uuid4().hex
            yield EventSequence(session.session_id, turn).make("turn.failed", code="empty_question")
            return
        if len(question) > MAX_QUESTION_CHARS:
            session = self.sessions.get_or_create(session_id)
            turn = turn_id or uuid.uuid4().hex
            yield EventSequence(session.session_id, turn).make(
                "turn.failed", code="question_too_long", max_chars=MAX_QUESTION_CHARS
            )
            return

        session = self.sessions.get_or_create(session_id)
        _, turn_id, cancel_event = self.sessions.begin_turn(session.session_id, turn_id)
        sequence = EventSequence(session.session_id, turn_id)
        history = self.sessions.history(session.session_id)
        reply_mode = short_reply_mode(question)
        basis = (
            "conversation_reply"
            if reply_mode
            else retrieval_basis(self.search, question, category, locale=locale)
        )
        retrieval_query = localized_search_query(question, locale, basis)
        answer_parts: list[str] = []
        candidates: tuple[HeritageItem, ...] = ()

        try:
            yield sequence.make("turn.started", question=question, locale=locale)
            if cancel_event.is_set():
                yield sequence.make(
                    "turn.cancelled", reason=self._cancel_reason(session.session_id, turn_id)
                )
                return

            if is_greeting(question, locale):
                answer = localized_copy(locale, "greeting")
                self.sessions.append(
                    session.session_id,
                    ConversationTurn(
                        turn_id=turn_id,
                        question=question,
                        answer=answer,
                        source_ids=(),
                        locale=locale,
                    ),
                )
                yield sequence.make("response.text.delta", delta=answer, locale=locale)
                yield sequence.make("response.sources", sources=[])
                yield sequence.make(
                    "turn.completed",
                    answer=answer,
                    confidence=1.0,
                    suggested_questions=localized_greeting_suggestions(locale),
                    locale=locale,
                )
                return

            yield sequence.make("retrieval.started")
            candidate_limit_value = (
                self.max_candidates
                if basis == "multilingual_catalogue"
                else self._candidate_limit(question, category)
            )
            result = (
                SearchResponse(items=(), total=0)
                if basis in {"none", "conversation_reply"}
                else await asyncio.to_thread(
                    self.search.search,
                    retrieval_query,
                    category=category,
                    limit=candidate_limit_value,
                )
            )
            if (
                not reply_mode
                and result.total > candidate_limit_value
                and (
                    basis == "multilingual_catalogue"
                    or is_scope_browse(self.search, question, category)
                )
            ):
                offset = exploration_offset(
                    session.session_id,
                    turn_id,
                    retrieval_query,
                    result.total,
                    candidate_limit_value,
                )
                result = await asyncio.to_thread(
                    self.search.search,
                    retrieval_query,
                    category=category,
                    limit=candidate_limit_value,
                    offset=offset,
                )
                LOGGER.info(
                    "[trace=%s turn=%s] retrieval.window offset=%s total=%s",
                    session.session_id,
                    turn_id,
                    offset,
                    result.total,
                )

            candidates = tuple(result.items)
            LOGGER.info(
                "[trace=%s turn=%s] retrieval.completed basis=%s history_turns=%s total=%s candidates=%s candidate_titles=%s",
                session.session_id,
                turn_id,
                basis,
                len(history),
                result.total,
                len(candidates),
                "|".join(item.title for item in candidates) or "-",
            )
            yield sequence.make(
                "retrieval.completed", total=result.total, source_count=len(candidates)
            )
            if cancel_event.is_set():
                yield sequence.make(
                    "turn.cancelled", reason=self._cancel_reason(session.session_id, turn_id)
                )
                return

            configured = getattr(self.llm, "api_key", object())
            api_key_configured = not (
                configured is None or (isinstance(configured, str) and not configured.strip())
            )
            if api_key_configured:
                messages = self._messages(
                    question,
                    candidates,
                    history,
                    short_reply_mode=reply_mode,
                    retrieval_basis=basis,
                    locale=locale,
                )
                try:
                    llm_started = time.perf_counter()
                    first_delta_at = None
                    delta_index = 0
                    text_chars = 0
                    next_progress_chars = 100
                    LOGGER.info(
                        "[trace=%s turn=%s] llm.request.start attempts=%s first_token_timeout=%.3fs candidates=%s history_turns=%s retrieval_basis=%s",
                        session.session_id,
                        turn_id,
                        AI_FIRST_TOKEN_MAX_ATTEMPTS,
                        AI_FIRST_TOKEN_TIMEOUT,
                        len(candidates),
                        len(history),
                        basis,
                    )

                    def start_provider_stream():
                        return self.llm.stream_chat(messages, temperature=0.2, max_tokens=700)

                    async for delta in stream_with_first_token_retry(
                        start_provider_stream,
                        cancel_event,
                        timeout=AI_FIRST_TOKEN_TIMEOUT,
                        max_attempts=AI_FIRST_TOKEN_MAX_ATTEMPTS,
                        log_context=f"trace={session.session_id} turn={turn_id}",
                    ):
                        if not delta:
                            continue
                        if first_delta_at is None:
                            first_delta_at = time.perf_counter()
                            LOGGER.info(
                                "[trace=%s turn=%s] llm.first_text_delta +%.3fs",
                                session.session_id,
                                turn_id,
                                first_delta_at - llm_started,
                            )
                        answer_parts.append(delta)
                        delta_index += 1
                        text_chars += len(delta)
                        if text_chars >= next_progress_chars:
                            LOGGER.info(
                                "[trace=%s turn=%s] llm.text.progress chunks=%s chars=%s",
                                session.session_id,
                                turn_id,
                                delta_index,
                                text_chars,
                            )
                            next_progress_chars += 100
                        yield sequence.make("response.text.delta", delta=delta, locale=locale)

                    if cancel_event.is_set():
                        yield sequence.make(
                            "turn.cancelled", reason=self._cancel_reason(session.session_id, turn_id)
                        )
                        return
                    LOGGER.info(
                        "[trace=%s turn=%s] llm.stream.complete +%.3fs chunks=%s chars=%s",
                        session.session_id,
                        turn_id,
                        time.perf_counter() - llm_started,
                        delta_index,
                        text_chars,
                    )
                except asyncio.CancelledError:
                    raise
                except LLMFirstTokenTimeout as exc:
                    LOGGER.error(
                        "[trace=%s turn=%s] llm.failed code=llm_first_token_timeout attempts=%s",
                        session.session_id,
                        turn_id,
                        exc.attempts,
                    )
                    yield sequence.make(
                        "turn.failed", code="llm_first_token_timeout", attempts=exc.attempts
                    )
                    return
                except LLMEmptyStream as exc:
                    LOGGER.error(
                        "[trace=%s turn=%s] llm.failed code=llm_empty_stream attempts=%s",
                        session.session_id,
                        turn_id,
                        exc.attempts,
                    )
                    yield sequence.make(
                        "turn.failed", code="llm_empty_stream", attempts=exc.attempts
                    )
                    return
                except Exception:
                    LOGGER.error(
                        "[trace=%s turn=%s] llm.failed code=llm_unavailable",
                        session.session_id,
                        turn_id,
                        exc_info=True,
                    )
                    yield sequence.make("turn.failed", code="llm_unavailable")
                    return

            if cancel_event.is_set():
                yield sequence.make(
                    "turn.cancelled", reason=self._cancel_reason(session.session_id, turn_id)
                )
                return

            answer = "".join(answer_parts).strip() or fallback_answer(
                question, candidates, history=history, locale=locale
            )
            if not answer_parts:
                yield sequence.make("response.text.delta", delta=answer, locale=locale)

            source_items = used_sources(answer, candidates)
            answer_confidence = confidence(source_items, answer)
            source_ids = tuple(item.id for item in source_items)
            self.sessions.append(
                session.session_id,
                ConversationTurn(
                    turn_id=turn_id,
                    question=question,
                    answer=answer,
                    source_ids=source_ids,
                    locale=locale,
                ),
            )
            source_payload = [item_to_dict(item) for item in source_items]
            yield sequence.make("response.sources", sources=source_payload)
            LOGGER.info(
                "[trace=%s turn=%s] text.complete chars=%s sources=%s",
                session.session_id,
                turn_id,
                len(answer),
                len(source_payload),
            )
            yield sequence.make(
                "turn.completed",
                answer=answer,
                confidence=answer_confidence,
                suggested_questions=suggestions(source_items, locale=locale),
                locale=locale,
            )
        finally:
            self.sessions.finish_turn(session.session_id, turn_id, cancel_event)

    def _cancel_reason(self, session_id: str, turn_id: str) -> str:
        return self.sessions.cancel_reason(session_id, turn_id) or "client_cancelled"

    def _candidate_limit(self, question: str, category: str = "") -> int:
        return candidate_limit(self.search, question, category, self.max_candidates)

    def _messages(
        self,
        question: str,
        candidates: Sequence[HeritageItem],
        history: Sequence[ConversationTurn],
        *,
        short_reply_mode: str | None = None,
        retrieval_basis: str | None = None,
        locale: str = DEFAULT_LOCALE,
    ) -> list[dict[str, str]]:
        return build_messages(
            question,
            candidates,
            history,
            short_reply_mode=short_reply_mode or globals()["short_reply_mode"](question),
            retrieval_basis=retrieval_basis or ("retrieval" if candidates else "none"),
            locale=locale,
            max_context_chars=AI_MAX_CONTEXT_CHARS,
        )

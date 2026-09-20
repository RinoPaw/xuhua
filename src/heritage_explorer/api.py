"""FastAPI/ASGI transport for the assistant core."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import time
from typing import Any

import edge_tts
from fastapi import FastAPI, HTTPException, Path as ApiPath, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from . import __version__
from .admission import (
    AdmissionController,
    AdmissionMiddleware,
    AdmissionPolicy,
    client_key_from_scope,
)
from .assistant import AssistantService
from .asr_normalization import normalize_asr_final, prepare_asr_normalization
from .config import (
    CHAT_MAX_CONCURRENCY,
    CHAT_MAX_PER_CLIENT_PER_MINUTE,
    CHAT_MAX_PER_MINUTE,
    FRONTEND_DIR,
    TTS_MAX_CONCURRENCY,
    TTS_MAX_PER_CLIENT_PER_MINUTE,
    TTS_MAX_PER_MINUTE,
    VOICE_MAX_CONCURRENCY,
    VOICE_MAX_PER_CLIENT_PER_MINUTE,
    VOICE_MAX_PER_MINUTE,
    XF_API_KEY,
    XF_API_SECRET,
    XF_APP_ID,
    XF_ASR_HOST,
)
from .dataset import item_to_dict
from .language import detect_locale, get_language_profile, normalize_locale_hint
from .tts_tickets import TtsTicketCapacity, TtsTicketStore
from .voice import XfyunStream
from .voice_transport import register_voice_route


MAX_CHAT_CHARS = 4000
MAX_SEARCH_CHARS = 512
MAX_SESSION_ID_CHARS = 128
MAX_TURN_ID_CHARS = 128
MAX_TTS_CHARS = 4000
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    session_id: str | None = Field(default=None, max_length=MAX_SESSION_ID_CHARS)
    category: str = Field(default="", max_length=200)
    locale_hint: str = Field(default="", max_length=64)


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)
    locale: str = Field(default="", max_length=64)
    trace_id: str = Field(default="", max_length=128)
    segment: int = Field(default=0, ge=0, le=999)
    reason: str = Field(default="", max_length=40)


def create_default_admission_controller() -> AdmissionController:
    return AdmissionController(
        {
            "chat": AdmissionPolicy(
                CHAT_MAX_CONCURRENCY,
                CHAT_MAX_PER_MINUTE,
                CHAT_MAX_PER_CLIENT_PER_MINUTE,
            ),
            "tts": AdmissionPolicy(
                TTS_MAX_CONCURRENCY,
                TTS_MAX_PER_MINUTE,
                TTS_MAX_PER_CLIENT_PER_MINUTE,
            ),
            "voice": AdmissionPolicy(
                VOICE_MAX_CONCURRENCY,
                VOICE_MAX_PER_MINUTE,
                VOICE_MAX_PER_CLIENT_PER_MINUTE,
            ),
        }
    )


def create_app(
    *,
    assistant: AssistantService | None = None,
    admission: AdmissionController | None = None,
) -> FastAPI:
    assistant = assistant or AssistantService()
    search = assistant.search
    sessions = assistant.sessions
    admission = admission or create_default_admission_controller()
    kb = search.knowledge_base
    tts_tickets = TtsTicketStore()
    voice_available = bool(
        XF_APP_ID.strip()
        and XF_API_KEY.strip()
        and XF_API_SECRET.strip()
        and XF_ASR_HOST.strip()
    )
    prepare_asr_normalization(kb)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        close = getattr(assistant, "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(title="叙华", version=__version__, lifespan=lifespan)
    app.add_middleware(AdmissionMiddleware, controller=admission)

    @app.get("/healthz")
    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        level_order = {"国家级": 0, "省级": 1, "市级": 2, "县级": 3}
        levels = sorted(
            {item.level for item in kb.items if item.level},
            key=lambda value: (level_order.get(value, 99), value),
        )
        return {
            "app_version": __version__,
            "schema_version": kb.schema_version,
            "generated_at": kb.generated_at,
            "source": kb.source,
            "item_count": len(kb.items),
            "category_count": len(kb.categories),
            "levels": levels,
            "capabilities": {
                "text_chat": True,
                "realtime_voice": voice_available,
                "voice_provider": "xfyun" if voice_available else "",
            },
        }

    @app.get("/api/categories")
    async def categories() -> list[dict[str, Any]]:
        return [
            {"id": category.id, "name": category.name, "item_count": category.item_count}
            for category in kb.categories
        ]

    @app.post("/api/tts")
    async def prepare_speech(
        body: TtsRequest,
        request: Request,
        response: Response,
    ) -> dict[str, str]:
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="empty_text")
        try:
            token = tts_tickets.issue(
                text=text,
                locale=body.locale.strip(),
                trace_id=body.trace_id.strip(),
                segment=body.segment,
                reason=body.reason.strip(),
                client_id=client_key_from_scope(request.scope),
            )
        except TtsTicketCapacity as exc:
            raise HTTPException(status_code=503, detail="tts_ticket_capacity") from exc
        response.headers["Cache-Control"] = "no-store"
        return {"token": token}

    @app.get("/api/tts/{token}")
    async def synthesize_speech(
        token: str = ApiPath(..., min_length=16, max_length=128),
    ) -> StreamingResponse:
        ticket = tts_tickets.get(token)
        if ticket is None:
            raise HTTPException(status_code=404, detail="tts_ticket_not_found")

        language_profile = get_language_profile(
            normalize_locale_hint(ticket.locale) or detect_locale(ticket.text)
        )
        started = time.perf_counter()
        LOGGER.info(
            "[trace=%s segment=%s] tts.request.start reason=%s chars=%s locale=%s",
            ticket.trace_id or "-",
            ticket.segment,
            ticket.reason or "unspecified",
            len(ticket.text),
            language_profile.code,
        )

        async def audio_stream() -> AsyncIterator[bytes]:
            communicate = edge_tts.Communicate(
                ticket.text,
                voice=language_profile.tts_voice,
                rate="-2%",
                pitch="+0Hz",
            )
            first_chunk = True
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    if first_chunk:
                        first_chunk = False
                        LOGGER.info(
                            "[trace=%s segment=%s] tts.first_audio_chunk +%.3fs",
                            ticket.trace_id or "-",
                            ticket.segment,
                            time.perf_counter() - started,
                        )
                    yield chunk["data"]
            LOGGER.info(
                "[trace=%s segment=%s] tts.stream.complete +%.3fs",
                ticket.trace_id or "-",
                ticket.segment,
                time.perf_counter() - started,
            )

        return StreamingResponse(
            audio_stream(),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "X-Speech-Locale": language_profile.code,
            },
        )

    @app.get("/api/items")
    async def items(
        q: str = Query(default="", max_length=MAX_SEARCH_CHARS),
        category: str = Query(default="", max_length=200),
        province: str = Query(default="", max_length=200),
        level: str = Query(default="", max_length=100),
        district: str = Query(default="", max_length=200),
        keywords: str = Query(default="", max_length=MAX_SEARCH_CHARS),
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0, le=100000),
    ) -> dict[str, Any]:
        result = await asyncio.to_thread(
            search.search,
            q,
            category=category,
            province=province,
            level=level,
            district=district,
            keywords=keywords,
            limit=limit,
            offset=offset,
        )
        return {
            "total": result.total,
            "limit": min(max(limit, 1), 100),
            "offset": max(offset, 0),
            "items": [item_to_dict(item) for item in result.items],
        }

    @app.get("/api/items/{item_id}")
    async def item_detail(
        item_id: str = ApiPath(..., min_length=1, max_length=200),
    ) -> dict[str, Any]:
        item = kb.get(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="item_not_found")
        return await asyncio.to_thread(
            item_to_dict,
            item,
            include_content=True,
            include_enrichment=True,
        )

    @app.post("/api/chat", response_class=EventSourceResponse)
    async def chat(body: ChatRequest) -> AsyncIterator[ServerSentEvent]:
        question = body.question.strip()
        session_id = body.session_id.strip() if body.session_id else None
        category = body.category.strip()
        locale_hint = body.locale_hint.strip()

        async for assistant_event in assistant.stream_turn(
            question,
            session_id=session_id,
            category=category,
            locale_hint=locale_hint,
        ):
            yield ServerSentEvent(
                data=assistant_event.to_dict(),
                event=assistant_event.type,
                id=str(assistant_event.seq),
            )

    @app.post("/api/chat/{session_id}/turn/{turn_id}/cancel")
    async def cancel_turn(
        session_id: str = ApiPath(..., min_length=1, max_length=MAX_SESSION_ID_CHARS),
        turn_id: str = ApiPath(..., min_length=1, max_length=MAX_TURN_ID_CHARS),
    ) -> dict[str, Any]:
        cancelled = sessions.cancel_turn(session_id, turn_id)
        return {"cancelled": cancelled, "session_id": session_id, "turn_id": turn_id}

    register_voice_route(
        app,
        assistant=assistant,
        sessions=sessions,
        knowledge_base=kb,
        available=voice_available,
        app_id=XF_APP_ID,
        api_key=XF_API_KEY,
        api_secret=XF_API_SECRET,
        asr_host=XF_ASR_HOST,
        normalize_final=normalize_asr_final,
        stream_factory=XfyunStream,
        max_session_id_chars=MAX_SESSION_ID_CHARS,
    )

    if FRONTEND_DIR.is_dir():
        app.frontend("/", directory=FRONTEND_DIR, fallback="index.html")

    return app


app = create_app()


def main() -> None:
    """Run the local ASGI server."""

    import uvicorn

    from .config import DEBUG, HOST, PORT

    uvicorn.run("heritage_explorer.api:app", host=HOST, port=PORT, reload=DEBUG)


__all__ = ["app", "create_app", "create_default_admission_controller", "main"]

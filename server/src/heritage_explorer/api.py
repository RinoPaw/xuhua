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
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .admission import (
    AdmissionController,
    AdmissionDenied,
    AdmissionMiddleware,
    AdmissionPolicy,
    client_key_from_scope,
)
from .assistant import AssistantService
from .asr_normalization import normalize_asr_final, prepare_asr_normalization
from .config import (
    ASR_MAX_CONCURRENCY,
    ASR_MAX_PER_CLIENT_PER_MINUTE,
    ASR_MAX_PER_MINUTE,
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
from .logging_setup import configure_application_logging
from .request_limits import RequestBodyLimitMiddleware
from .tts_tickets import TtsTicketCapacity, TtsTicketStore
from .voice import XfyunStream
from .voice_transport import MAX_VOICE_FRAME_BYTES, register_voice_route


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
    trace_id: str = Field(default="", max_length=128, pattern=r"^[A-Za-z0-9._:-]*$")
    segment: int = Field(default=0, ge=0, le=999)
    reason: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9._:-]*$")


def create_default_admission_controller() -> AdmissionController:
    tts_policy = AdmissionPolicy(
        TTS_MAX_CONCURRENCY,
        TTS_MAX_PER_MINUTE,
        TTS_MAX_PER_CLIENT_PER_MINUTE,
    )
    return AdmissionController(
        {
            "chat": AdmissionPolicy(
                CHAT_MAX_CONCURRENCY,
                CHAT_MAX_PER_MINUTE,
                CHAT_MAX_PER_CLIENT_PER_MINUTE,
            ),
            "asr": AdmissionPolicy(
                ASR_MAX_CONCURRENCY,
                ASR_MAX_PER_MINUTE,
                ASR_MAX_PER_CLIENT_PER_MINUTE,
            ),
            "tts_ticket": tts_policy,
            "tts": tts_policy,
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
        # Uvicorn configures its own loggers but does not guarantee a root
        # handler for heritage_explorer.*. Respect host-provided handlers.
        configure_application_logging()
        yield
        close = getattr(assistant, "aclose", None)
        if close is not None:
            await close()

    app = FastAPI(title="叙华", version=__version__, lifespan=lifespan)
    app.add_middleware(AdmissionMiddleware, controller=admission)
    app.add_middleware(RequestBodyLimitMiddleware)

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
        request: Request,
        token: str = ApiPath(..., min_length=16, max_length=128),
        progressive: bool = Query(default=False, alias="stream"),
    ) -> Response:
        """Stream early audio when requested, retaining buffered retries.

        The first audio chunk must be obtained before committing response
        headers, so startup/provider errors remain ordinary HTTP failures.
        Subsequent streaming failures abort playback rather than silently
        returning a successful truncated answer. A retry always uses the
        original fully buffered response to avoid repeated partial playback.
        """

        client_id = client_key_from_scope(request.scope)
        ticket = tts_tickets.get(token, client_id=client_id)
        if ticket is None:
            raise HTTPException(status_code=404, detail="tts_ticket_not_found")
        try:
            lease = await admission.acquire("tts", client_id)
        except AdmissionDenied as exc:
            status = 503 if exc.reason == "capacity" else 429
            raise HTTPException(
                status_code=status,
                detail=f"tts_{exc.reason}",
                headers={"Retry-After": str(exc.retry_after)},
            ) from exc

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

        first_chunk_logged = False
        bytes_sent = 0
        try:
            communicate = edge_tts.Communicate(
                ticket.text,
                voice=language_profile.tts_voice,
                rate="-2%",
                pitch="+0Hz",
            )
            upstream = communicate.stream()
        except Exception as exc:
            await lease.release()
            LOGGER.warning(
                "[trace=%s segment=%s] tts.provider.failed locale=%s reason=%s",
                ticket.trace_id or "-",
                ticket.segment,
                language_profile.code,
                type(exc).__name__,
            )
            raise HTTPException(status_code=502, detail="tts_provider_unavailable") from None

        async def audio_chunks() -> AsyncIterator[bytes]:
            nonlocal first_chunk_logged, bytes_sent
            outcome = "cancelled"
            try:
                async for chunk in upstream:
                    if chunk.get("type") != "audio" or not chunk.get("data"):
                        continue
                    data = chunk["data"]
                    if not first_chunk_logged:
                        first_chunk_logged = True
                        LOGGER.info(
                            "[trace=%s segment=%s] tts.first_audio_chunk +%.3fs",
                            ticket.trace_id or "-",
                            ticket.segment,
                            time.perf_counter() - started,
                        )
                    bytes_sent += len(data)
                    yield data
                outcome = "completed" if first_chunk_logged else "failed"
                if first_chunk_logged:
                    LOGGER.info(
                        "[trace=%s segment=%s] tts.complete +%.3fs bytes=%s",
                        ticket.trace_id or "-",
                        ticket.segment,
                        time.perf_counter() - started,
                        bytes_sent,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                outcome = "failed"
                raise
            finally:
                LOGGER.info(
                    "[trace=%s segment=%s] tts.finish outcome=%s elapsed_ms=%.1f bytes=%s first_chunk=%s",
                    ticket.trace_id or "-",
                    ticket.segment,
                    outcome,
                    (time.perf_counter() - started) * 1000,
                    bytes_sent,
                    first_chunk_logged,
                )
                close = getattr(upstream, "aclose", None)
                if close is not None:
                    await close()

        audio = audio_chunks()

        async def release_audio() -> None:
            # Upstream generators may themselves fail during close(). A failed
            # teardown must never retain TTS admission capacity.
            try:
                await audio.aclose()
            finally:
                await lease.release()

        streaming = progressive and "tts_retry" not in request.query_params
        if streaming:
            # The network/browser can start consuming this MP3 before Edge
            # finishes its remaining chunks.
            try:
                first = await anext(audio, None)
            except asyncio.CancelledError:
                await release_audio()
                raise
            except Exception as exc:
                await release_audio()
                LOGGER.warning(
                    "[trace=%s segment=%s] tts.provider.failed locale=%s reason=%s",
                    ticket.trace_id or "-",
                    ticket.segment,
                    language_profile.code,
                    type(exc).__name__,
                )
                raise HTTPException(status_code=502, detail="tts_provider_unavailable") from None
            if not first:
                await release_audio()
                raise HTTPException(status_code=502, detail="tts_provider_no_audio")

            async def progressive_audio() -> AsyncIterator[bytes]:
                try:
                    yield first
                    async for data in audio:
                        yield data
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.warning(
                        "[trace=%s segment=%s] tts.provider.interrupted locale=%s reason=%s",
                        ticket.trace_id or "-",
                        ticket.segment,
                        language_profile.code,
                        type(exc).__name__,
                    )
                    # Never turn a partially spoken response into a successful
                    # short response. Abort the HTTP stream and let HTMLAudio
                    # report an error (without replaying already heard audio).
                    raise RuntimeError("tts_stream_interrupted") from None
                finally:
                    await release_audio()

            return StreamingResponse(
                progressive_audio(),
                media_type="audio/mpeg",
                headers={
                    "Cache-Control": "no-store",
                    "Accept-Ranges": "none",
                    "X-Speech-Locale": language_profile.code,
                },
            )

        # Buffered fallback provides a reliable replayable MP3 for legacy
        # callers and for attempts with a tts_retry query parameter.
        payload = bytearray()
        try:
            async for data in audio:
                payload.extend(data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "[trace=%s segment=%s] tts.provider.failed locale=%s reason=%s",
                ticket.trace_id or "-",
                ticket.segment,
                language_profile.code,
                type(exc).__name__,
            )
            raise HTTPException(status_code=502, detail="tts_provider_unavailable") from None
        finally:
            await release_audio()

        if not payload:
            raise HTTPException(status_code=502, detail="tts_provider_no_audio")

        return Response(
            content=bytes(payload),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "Content-Length": str(len(payload)),
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
        admission=admission,
    )

    if FRONTEND_DIR.is_dir():
        app.frontend("/", directory=FRONTEND_DIR, fallback="index.html")

    return app


app = create_app()


def main() -> None:
    """Run the local ASGI server."""

    import uvicorn

    from .config import DEBUG, HOST, PORT

    uvicorn.run(
        "heritage_explorer.api:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        workers=1,
        ws_max_size=MAX_VOICE_FRAME_BYTES,
    )


__all__ = ["app", "create_app", "create_default_admission_controller", "main"]

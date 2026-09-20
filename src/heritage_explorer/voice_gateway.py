"""Compatibility facade for the realtime browser voice transport."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI

from .assistant import AssistantService
from .asr_normalization import normalize_asr_final as _default_normalize_asr_final
from .dataset import KnowledgeBase
from .sessions import SessionStore
from .voice import XfyunStream
from .voice_session import (
    MAX_VOICE_CONTEXT_TITLES,
    MAX_VOICE_RECENT_ITEMS,
    contains_spoken_text,
)
from .voice_transport import register_voice_route as _register_voice_route


# Compatibility surface: api.py and older tests monkeypatch this symbol before
# calling create_app(). The facade injects the current value into the runtime.
normalize_asr_final = _default_normalize_asr_final


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
    _register_voice_route(
        app,
        assistant=assistant,
        sessions=sessions,
        knowledge_base=knowledge_base,
        app_id=app_id,
        api_key=api_key,
        api_secret=api_secret,
        asr_host=asr_host,
        stream_factory=stream_factory,
        normalize_final=normalize_asr_final,
        max_session_id_chars=max_session_id_chars,
    )


__all__ = [
    "MAX_VOICE_CONTEXT_TITLES",
    "MAX_VOICE_RECENT_ITEMS",
    "contains_spoken_text",
    "normalize_asr_final",
    "register_voice_route",
]

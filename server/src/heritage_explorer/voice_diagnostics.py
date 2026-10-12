"""Opt-in, local-only voice diagnostics. Never log secrets or raw audio."""

from __future__ import annotations

import logging
import os
import re

LOGGER = logging.getLogger("heritage_explorer.voice_diagnostics")
LOGGER.setLevel(logging.INFO)
_TRUE = frozenset({"1", "true", "yes", "on"})
_BROWSER_EVENTS = frozenset({
    "wake.local.listening", "wake.local.detected", "wake.local.speech_unmatched",
    "wake.local.stopped", "wake.remote.connected", "wake.remote.failed",
    "voice.tts.playing", "voice.tts.failed", "voice.tts.complete",
    "voice.tts.segment_complete", "voice.outcome",
})
_TOKEN = re.compile(r"^[a-zA-Z0-9_-]{1,72}$")


def diagnostics_enabled() -> bool:
    return os.getenv("XUHUA_LOCAL_VOICE_DIAGNOSTICS", "").lower() in _TRUE


def safe_text(value: object, limit: int = 400) -> str:
    """Use repr to keep each utterance on one log line."""
    return repr(str(value or "")[:limit])


def log_voice_text(event: str, *, connection: str, utterance: str, text: object) -> None:
    if diagnostics_enabled():
        LOGGER.info(
            "voice.dialogue event=%s connection=%s utterance=%s text=%s",
            event, connection, utterance, safe_text(text),
        )


def log_browser_diagnostic(
    *, event: str, connection: str = "-", trace: str = "-",
    segment: int = -1, elapsed_ms: float = 0, level: float = 0,
) -> bool:
    if not diagnostics_enabled() or event not in _BROWSER_EVENTS:
        return False
    LOGGER.info(
        "voice.browser event=%s connection=%s trace=%s segment=%s elapsed_ms=%.1f level=%.4f",
        event,
        connection if _TOKEN.fullmatch(connection) else "-",
        trace if _TOKEN.fullmatch(trace) else "-",
        segment, elapsed_ms, level,
    )
    return True

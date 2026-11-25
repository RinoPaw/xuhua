"""Standalone Shizha application with its own assistant, sessions and admission limits."""

from fastapi import FastAPI

from .admission import AdmissionController
from .api import create_app
from .config import FRONTEND_DIR
from .shizha import create_assistant, normalize_asr_final


def create_shizha_app(*, admission: AdmissionController | None = None) -> FastAPI:
    app = create_app(
        assistant=create_assistant(),
        admission=admission,
        agent_name="\u8bc6\u8bc8",
        voice_normalizer=normalize_asr_final,
    )

    if FRONTEND_DIR.is_dir():
        app.frontend("/", directory=FRONTEND_DIR, fallback=None)

    return app

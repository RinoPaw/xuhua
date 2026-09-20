"""Application paths and required environment-backed settings."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def env_path(name: str) -> Path:
    path = Path(os.environ[name])
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def positive_int(name: str, default: int | None = None) -> int:
    raw = os.environ[name] if default is None else os.environ.get(name, str(default))
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def positive_float(name: str, default: float | None = None) -> float:
    raw = os.environ[name] if default is None else os.environ.get(name, str(default))
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def port_number(name: str) -> int:
    value = positive_int(name)
    if value > 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


DATASET_PATH = env_path("DATASET_PATH")
FRONTEND_DIR = env_path("FRONTEND_DIR")
HOST = os.environ["HOST"]
PORT = port_number("PORT")
DEBUG = os.environ["DEBUG"] == "1"

AI_API_KEY = os.environ["AI_API_KEY"]
AI_BASE_URL = os.environ["AI_BASE_URL"]
AI_MODEL = os.environ["AI_MODEL"]
AI_TIMEOUT = positive_float("AI_TIMEOUT")
AI_FIRST_TOKEN_TIMEOUT = positive_float("AI_FIRST_TOKEN_TIMEOUT")
AI_FIRST_TOKEN_MAX_ATTEMPTS = min(max(int(os.environ["AI_FIRST_TOKEN_MAX_ATTEMPTS"]), 1), 2)
AI_MAX_CONTEXT_CHARS = positive_int("AI_MAX_CONTEXT_CHARS")

XF_APP_ID = os.environ["XF_APP_ID"]
XF_API_KEY = os.environ["XF_API_KEY"]
XF_API_SECRET = os.environ["XF_API_SECRET"]
XF_ASR_HOST = os.environ["XF_ASR_HOST"]

CHAT_MAX_CONCURRENCY = positive_int("CHAT_MAX_CONCURRENCY", 8)
CHAT_MAX_PER_MINUTE = positive_int("CHAT_MAX_PER_MINUTE", 60)
CHAT_MAX_PER_CLIENT_PER_MINUTE = positive_int("CHAT_MAX_PER_CLIENT_PER_MINUTE", 20)
TTS_MAX_CONCURRENCY = positive_int("TTS_MAX_CONCURRENCY", 12)
TTS_MAX_PER_MINUTE = positive_int("TTS_MAX_PER_MINUTE", 240)
TTS_MAX_PER_CLIENT_PER_MINUTE = positive_int("TTS_MAX_PER_CLIENT_PER_MINUTE", 80)
VOICE_MAX_CONCURRENCY = positive_int("VOICE_MAX_CONCURRENCY", 4)
VOICE_MAX_PER_MINUTE = positive_int("VOICE_MAX_PER_MINUTE", 30)
VOICE_MAX_PER_CLIENT_PER_MINUTE = positive_int("VOICE_MAX_PER_CLIENT_PER_MINUTE", 8)

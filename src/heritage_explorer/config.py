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


DATASET_PATH = env_path("DATASET_PATH")
FRONTEND_DIR = env_path("FRONTEND_DIR")
HOST = os.environ["HOST"]
PORT = int(os.environ["PORT"])
DEBUG = os.environ["DEBUG"] == "1"

AI_API_KEY = os.environ["AI_API_KEY"]
AI_BASE_URL = os.environ["AI_BASE_URL"]
AI_MODEL = os.environ["AI_MODEL"]
AI_TIMEOUT = int(os.environ["AI_TIMEOUT"])
AI_FIRST_TOKEN_TIMEOUT = float(os.environ["AI_FIRST_TOKEN_TIMEOUT"])
AI_FIRST_TOKEN_MAX_ATTEMPTS = min(max(int(os.environ["AI_FIRST_TOKEN_MAX_ATTEMPTS"]), 1), 2)
AI_MAX_CONTEXT_CHARS = int(os.environ["AI_MAX_CONTEXT_CHARS"])

XF_APP_ID = os.environ["XF_APP_ID"]
XF_API_KEY = os.environ["XF_API_KEY"]
XF_API_SECRET = os.environ["XF_API_SECRET"]
XF_ASR_HOST = os.environ["XF_ASR_HOST"]

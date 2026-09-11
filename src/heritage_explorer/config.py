"""Application paths and environment-backed settings."""

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

# Browser duplex voice: streaming speech recognition through Xunfei IAT.
# Speech output is scheduled in the browser so barge-in can stop it immediately.
XF_APP_ID = os.environ["XF_APP_ID"]
XF_API_KEY = os.environ["XF_API_KEY"]
XF_API_SECRET = os.environ["XF_API_SECRET"]
XF_ASR_RES_ID = os.environ["XF_ASR_RES_ID"]
XF_ASR_HOST = os.environ["XF_ASR_HOST"]

EMBEDDING_API_KEY = os.environ["EMBEDDING_API_KEY"]
EMBEDDING_BASE_URL = os.environ["EMBEDDING_BASE_URL"]
EMBEDDING_MODEL = os.environ["EMBEDDING_MODEL"]
EMBEDDING_TIMEOUT = int(os.environ["EMBEDDING_TIMEOUT"])
EMBEDDING_BATCH_SIZE = int(os.environ["EMBEDDING_BATCH_SIZE"])
EMBEDDING_WORKERS = int(os.environ["EMBEDDING_WORKERS"])
EMBEDDING_REQUEST_TIMEOUT = float(os.environ["EMBEDDING_REQUEST_TIMEOUT"])
EMBEDDING_MAX_RETRIES = int(os.environ["EMBEDDING_MAX_RETRIES"])
EMBEDDING_RETRY_BACKOFF = float(os.environ["EMBEDDING_RETRY_BACKOFF"])
EMBEDDING_REQUEST_DELAY = float(os.environ["EMBEDDING_REQUEST_DELAY"])
EMBEDDING_INDEX_PATH = env_path("EMBEDDING_INDEX_PATH")
EMBEDDING_TEXT_MAX_CHARS = int(os.environ["EMBEDDING_TEXT_MAX_CHARS"])
EMBEDDING_MIN_SCORE = float(os.environ["EMBEDDING_MIN_SCORE"])
SEARCH_USE_EMBEDDING = os.environ["SEARCH_USE_EMBEDDING"] == "1"

"""Application paths and environment-backed settings."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    if path is None:
        path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def env_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


DATASET_PATH = env_path("DATASET_PATH", "data/processed/heritage_items.json")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5050"))
DEBUG = os.getenv("DEBUG", "0") == "1"

AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-v4-flash")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_CONTEXT_CHARS = int(os.getenv("AI_MAX_CONTEXT_CHARS", "5200"))
AI_AGENT_PLANNER = os.getenv("AI_AGENT_PLANNER", "1") == "1"

EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://api.vectorengine.ai/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_TIMEOUT = int(os.getenv("EMBEDDING_TIMEOUT", "60"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
EMBEDDING_WORKERS = int(os.getenv("EMBEDDING_WORKERS", "6"))
EMBEDDING_REQUEST_TIMEOUT = float(os.getenv("EMBEDDING_REQUEST_TIMEOUT", "5"))
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "4"))
EMBEDDING_RETRY_BACKOFF = float(os.getenv("EMBEDDING_RETRY_BACKOFF", "3"))
EMBEDDING_REQUEST_DELAY = float(os.getenv("EMBEDDING_REQUEST_DELAY", "0"))
EMBEDDING_INDEX_PATH = env_path(
    "EMBEDDING_INDEX_PATH",
    "data/embeddings/heritage_embeddings.json",
)
EMBEDDING_TEXT_MAX_CHARS = int(os.getenv("EMBEDDING_TEXT_MAX_CHARS", "1400"))
EMBEDDING_MIN_SCORE = float(os.getenv("EMBEDDING_MIN_SCORE", "0.15"))
SEARCH_USE_EMBEDDING = os.getenv("SEARCH_USE_EMBEDDING", "0") == "1"

VOLC_TTS_ENABLED = os.getenv("VOLC_TTS_ENABLED", "1") == "1"
VOLC_TTS_API_VERSION = os.getenv("VOLC_TTS_API_VERSION", "auto")
VOLC_TTS_ENDPOINT = os.getenv("VOLC_TTS_ENDPOINT", "https://openspeech.bytedance.com/api/v1/tts")
VOLC_TTS_V3_ENDPOINT = os.getenv(
    "VOLC_TTS_V3_ENDPOINT",
    "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
)
VOLC_TTS_API_KEY = os.getenv("VOLC_TTS_API_KEY", "")
VOLC_TTS_APP_ID = os.getenv("VOLC_TTS_APP_ID", "")
VOLC_TTS_ACCESS_TOKEN = os.getenv("VOLC_TTS_ACCESS_TOKEN", "")
VOLC_TTS_CLUSTER = os.getenv("VOLC_TTS_CLUSTER", "volcano_tts")
VOLC_TTS_RESOURCE_ID = os.getenv("VOLC_TTS_RESOURCE_ID", "volc.service_type.10029")
VOLC_TTS_VOICE_TYPE = os.getenv(
    "VOLC_TTS_VOICE_TYPE",
    "zh_female_gaolengyujie_emo_v2_mars_bigtts",
)
VOLC_TTS_EMOTION = os.getenv("VOLC_TTS_EMOTION", "coldness")
VOLC_TTS_EMOTION_SCALE = int(os.getenv("VOLC_TTS_EMOTION_SCALE", "4"))
VOLC_TTS_ENCODING = os.getenv("VOLC_TTS_ENCODING", "mp3")
VOLC_TTS_RATE = int(os.getenv("VOLC_TTS_RATE", "24000"))
VOLC_TTS_SPEED_RATIO = float(os.getenv("VOLC_TTS_SPEED_RATIO", "1.0"))
VOLC_TTS_VOLUME_RATIO = float(os.getenv("VOLC_TTS_VOLUME_RATIO", "1.0"))
VOLC_TTS_PITCH_RATIO = float(os.getenv("VOLC_TTS_PITCH_RATIO", "1.0"))
VOLC_TTS_TIMEOUT = float(os.getenv("VOLC_TTS_TIMEOUT", "20"))
VOLC_TTS_MAX_CHUNK_BYTES = int(os.getenv("VOLC_TTS_MAX_CHUNK_BYTES", "900"))
TTS_CACHE_DIR = env_path("TTS_CACHE_DIR", "tmp/tts")

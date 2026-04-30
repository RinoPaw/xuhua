"""Application paths and environment-backed settings."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
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
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
AI_MODEL = os.getenv("AI_MODEL", "glm-4-flash")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "60"))
AI_MAX_CONTEXT_CHARS = int(os.getenv("AI_MAX_CONTEXT_CHARS", "5200"))

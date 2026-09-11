from __future__ import annotations

import os


TEST_ENV = {
    "HOST": "127.0.0.1",
    "PORT": "5050",
    "DEBUG": "0",
    "DATASET_PATH": "data/processed/heritage_items.json",
    "FRONTEND_DIR": "frontend/dist/client",
    "AI_API_KEY": "",
    "AI_BASE_URL": "https://api.deepseek.com",
    "AI_MODEL": "deepseek-v4-flash",
    "AI_TIMEOUT": "60",
    "AI_FIRST_TOKEN_TIMEOUT": "8",
    "AI_FIRST_TOKEN_MAX_ATTEMPTS": "2",
    "AI_MAX_CONTEXT_CHARS": "5200",
    "XF_APP_ID": "",
    "XF_API_KEY": "",
    "XF_API_SECRET": "",
    "XF_ASR_HOST": "iat.xf-yun.com",
}

for name, value in TEST_ENV.items():
    os.environ.setdefault(name, value)

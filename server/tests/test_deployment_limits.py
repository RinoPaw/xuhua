from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUDGET_KEYS = (
    "CHAT_MAX_CONCURRENCY",
    "CHAT_MAX_PER_MINUTE",
    "CHAT_MAX_PER_CLIENT_PER_MINUTE",
    "TTS_MAX_CONCURRENCY",
    "TTS_MAX_PER_MINUTE",
    "TTS_MAX_PER_CLIENT_PER_MINUTE",
    "VOICE_MAX_CONCURRENCY",
    "VOICE_MAX_PER_MINUTE",
    "VOICE_MAX_PER_CLIENT_PER_MINUTE",
)


def test_budget_settings_are_visible_in_environment_template() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in BUDGET_KEYS:
        assert f"{key}=" in env_example


def test_environment_template_uses_current_model() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AI_MODEL=deepseek-flash" in env_example
    assert "deepseek-v4-flash" not in env_example


def test_nginx_configs_limit_expensive_public_routes() -> None:
    for filename in ("nginx-xuhua-http.conf", "nginx-xuhua-https.conf"):
        config = (ROOT / "deploy" / filename).read_text(encoding="utf-8")
        assert "zone=xuhua_chat_rate:10m rate=20r/m" in config
        assert "zone=xuhua_tts_ticket_rate:10m rate=80r/m" in config
        assert "zone=xuhua_tts_rate:10m rate=80r/m" in config
        assert "zone=xuhua_voice_rate:10m rate=8r/m" in config
        assert "zone=xuhua_voice_conn:10m" in config
        assert (
            "location = /api/chat {\n"
            "        client_max_body_size 64k;\n"
            "        client_body_timeout 10s;\n"
            "        limit_req zone=xuhua_chat_rate burst=4 nodelay;"
        ) in config
        assert (
            "location = /api/tts {\n"
            "        client_max_body_size 64k;\n"
            "        client_body_timeout 10s;\n"
            "        limit_req zone=xuhua_tts_ticket_rate burst=16 nodelay;"
        ) in config
        assert (
            "location ^~ /api/tts/ {\n"
            "        limit_req zone=xuhua_tts_rate burst=16 nodelay;"
        ) in config
        assert "location = /api/voice" in config
        assert "limit_req zone=xuhua_voice_rate" in config
        assert "limit_conn xuhua_voice_conn 2" in config
        assert "limit_req_status 429" in config
        assert "limit_conn_status 429" in config

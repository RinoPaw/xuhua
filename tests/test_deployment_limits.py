from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
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


def test_budget_settings_are_visible_in_local_and_render_templates() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    for key in BUDGET_KEYS:
        assert f"{key}=" in env_example
        assert f"- key: {key}" in render


def test_render_deploys_only_after_repository_checks_pass() -> None:
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "autoDeployTrigger: checksPass" in render
    assert "autoDeploy: true" not in render


def test_nginx_configs_limit_expensive_public_routes() -> None:
    for filename in ("nginx-xuhua-http.conf", "nginx-xuhua-https.conf"):
        config = (ROOT / "deploy" / filename).read_text(encoding="utf-8")
        assert "zone=xuhua_chat_rate:10m rate=20r/m" in config
        assert "zone=xuhua_tts_rate:10m rate=80r/m" in config
        assert "zone=xuhua_voice_rate:10m rate=8r/m" in config
        assert "zone=xuhua_voice_conn:10m" in config
        assert "location = /api/chat" in config
        assert "limit_req zone=xuhua_chat_rate" in config
        assert "location = /api/tts" in config
        assert "location ^~ /api/tts/" in config
        assert config.count("limit_req zone=xuhua_tts_rate") >= 2
        assert "location = /api/voice" in config
        assert "limit_req zone=xuhua_voice_rate" in config
        assert "limit_conn xuhua_voice_conn 2" in config
        assert "limit_req_status 429" in config
        assert "limit_conn_status 429" in config


def test_deploy_script_snapshots_restores_and_bounds_environment_history() -> None:
    deploy_script = ROOT / "deploy" / "xuhua-deploy.sh"
    subprocess.run(["bash", "-n", str(deploy_script)], check=True)
    script = deploy_script.read_text(encoding="utf-8")

    assert 'env_snapshot="$(env_snapshot_for "$commit_sha" "$env_revision")"' in script
    assert 'atomic_copy "$env_file" "$env_snapshot"' in script
    assert 'read -r candidate candidate_env_revision <"$pointer"' in script
    assert 'export XUHUA_ENV_FILE="$restore_env"' in script
    assert 'export XUHUA_ENV_REVISION="$restore_env_revision"' in script
    assert 'for snapshot in "$last_good_compose".*; do' in script
    assert '"$snapshot" == "$keep_current_env_file"' in script
    assert '"$snapshot" == "$keep_previous_env_file"' in script
    assert 'rm -f -- "$snapshot" || true' in script
    assert (
        "if wait_for_healthy; then\n"
        "  remember_success\n"
        "  deployment_succeeded=1\n"
        "  cleanup_old_artifacts\n"
        "  exit 0\n"
        "fi"
    ) in script

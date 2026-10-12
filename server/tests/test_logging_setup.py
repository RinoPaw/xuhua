"""Ensure voice diagnostics are visible under default server startup."""

from __future__ import annotations

import logging
from unittest.mock import Mock

from fastapi.testclient import TestClient

import heritage_explorer.api as api_module
import heritage_explorer.logging_setup as setup


def test_logging_bootstrap_adds_default_info_handler_only_without_host_configuration(
    monkeypatch,
) -> None:
    root = Mock()
    root.handlers = []
    configured = Mock()
    monkeypatch.setattr(setup.logging, "basicConfig", configured)

    assert setup.configure_application_logging(root_logger=root) is True
    configured.assert_called_once_with(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    root.handlers = [object()]
    assert setup.configure_application_logging(root_logger=root) is False
    configured.assert_called_once()


def test_server_lifespan_initializes_application_logging(monkeypatch) -> None:
    configured = []
    monkeypatch.setattr(
        api_module, "configure_application_logging", lambda: configured.append(True),
    )
    app = api_module.create_app()
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
    assert configured == [True]


def test_uvicorn_access_log_redacts_tts_ticket_and_query_without_dropping_status() -> None:
    from io import StringIO

    output = StringIO()
    logger = logging.Logger("uvicorn.access", logging.INFO)
    handler = logging.StreamHandler(output)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    setup.redact_uvicorn_tts_access_logs(access_logger=logger)
    setup.redact_uvicorn_tts_access_logs(access_logger=logger)
    assert len(logger.filters) == 1

    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:51000", "GET",
        "/api/tts/SECRET_TICKET_123?stream=1&token=ANOTHER_SECRET", "1.1", 200,
    )
    assert 'GET /api/tts/<redacted> HTTP/1.1" 200' in output.getvalue()
    assert "SECRET_TICKET_123" not in output.getvalue()
    assert "ANOTHER_SECRET" not in output.getvalue()
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:51000", "POST", "/api/tts", "1.1", 200,
    )
    assert 'POST /api/tts HTTP/1.1" 200' in output.getvalue()
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:51000", "GET", "/healthz", "1.1", 200,
    )
    assert 'GET /healthz HTTP/1.1" 200' in output.getvalue()


def test_access_redaction_is_not_affected_by_preexisting_logging_handlers(monkeypatch) -> None:
    import heritage_explorer.api as api

    calls = []
    monkeypatch.setattr(api, "configure_application_logging", lambda: calls.append("configured"))
    monkeypatch.setattr(api, "redact_uvicorn_tts_access_logs", lambda: calls.append("redacted"))
    with TestClient(api.create_app()) as client:
        assert client.get("/healthz").status_code == 200
    assert calls == ["configured", "redacted"]


def test_local_diagnostics_record_only_allowlisted_events(monkeypatch, caplog) -> None:
    import heritage_explorer.voice_diagnostics as diagnostics
    from heritage_explorer.api import create_app

    monkeypatch.setenv("XUHUA_LOCAL_VOICE_DIAGNOSTICS", "1")
    with TestClient(create_app(), client=("127.0.0.1", 40321)) as client:
        with caplog.at_level(logging.INFO, logger="heritage_explorer.voice_diagnostics"):
            result = client.post("/api/voice/diagnostics", json={
                "event": "wake.local.speech_unmatched",
                "connection": "-", "trace": "-", "level": 0.085,
                "elapsed_ms": 560,
            })
            assert result.status_code == 204
            payload = "\n".join(record.getMessage() for record in caplog.records)
            assert "voice.browser event=wake.local.speech_unmatched" in payload
            assert "elapsed_ms=560.0 level=0.0850" in payload

        for malicious in (
            {"event": "arbitrary", "connection": "-"},
            {"event": "wake.local.detected", "connection": "-", "text": "SECRET"},
            {"event": "wake.local.detected", "connection": "token=SECRET"},
            {"event": "wake.local.detected", "level": 1e100},
        ):
            assert client.post("/api/voice/diagnostics", json=malicious).status_code == 422
        assert client.post("/api/voice/diagnostics", json={
            "event": "wake.local.detected",
        }, headers={"Origin": "http://malicious.example"}).status_code == 403

    monkeypatch.delenv("XUHUA_LOCAL_VOICE_DIAGNOSTICS")
    with TestClient(create_app(), client=("127.0.0.1", 40322)) as client:
        assert client.post("/api/voice/diagnostics", json={
            "event": "wake.local.detected",
        }).status_code == 404
    assert diagnostics.log_browser_diagnostic(event="wake.local.detected") is False


def test_local_diagnostic_transcript_is_opt_in_and_single_line(monkeypatch, caplog) -> None:
    from heritage_explorer.voice_diagnostics import log_voice_text

    monkeypatch.delenv("XUHUA_LOCAL_VOICE_DIAGNOSTICS", raising=False)
    with caplog.at_level(logging.INFO, logger="heritage_explorer.voice_diagnostics"):
        log_voice_text("asr.segment", connection="conn1", utterance="1", text="PRIVATE")
    assert not any("PRIVATE" in item.getMessage() for item in caplog.records)

    monkeypatch.setenv("XUHUA_LOCAL_VOICE_DIAGNOSTICS", "1")
    with caplog.at_level(logging.INFO, logger="heritage_explorer.voice_diagnostics"):
        log_voice_text("asr.batch.canonical", connection="conn1", utterance="2",
                       text="叙华\n你在吗")
    lines = [item.getMessage() for item in caplog.records]
    assert len(lines) == 1
    assert "asr.batch.canonical" in lines[0]
    assert "叙华\\n你在吗" in lines[0]
    assert "\n" not in lines[0]

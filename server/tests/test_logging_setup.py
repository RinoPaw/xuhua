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

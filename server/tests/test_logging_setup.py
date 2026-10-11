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

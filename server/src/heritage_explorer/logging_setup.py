"""Small, non-invasive default logging configuration for standalone deployments."""

from __future__ import annotations

import logging


def configure_application_logging() -> bool:
    """Make application INFO diagnostics visible when the host has no root handler.

    Uvicorn installs handlers for its own named loggers, but a standalone
    heritage_explorer logger can otherwise have nowhere to emit INFO records.
    An application embedded in a larger host keeps that host's logging policy.
    """
    if logging.getLogger().handlers:
        return False
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return True

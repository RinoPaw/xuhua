"""Small, non-invasive default logging configuration for standalone deployments."""

from __future__ import annotations

import logging


def configure_application_logging(
    *, root_logger: logging.Logger | None = None
) -> bool:
    """Make application INFO diagnostics visible when the host has no root handler.

    Uvicorn installs handlers for its own named loggers, but a standalone
    heritage_explorer logger can otherwise have nowhere to emit INFO records.
    An application embedded in a larger host keeps that host's logging policy.
    """
    root = root_logger if root_logger is not None else logging.getLogger()
    if root.handlers:
        return False
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return True


class _TtsTicketAccessLogFilter(logging.Filter):
    """Redact bearer-like TTS ticket paths before Uvicorn formats access logs.

    Uvicorn's HTTP implementation supplies a positional tuple:
    (client_address, method, path_with_query, http_version, status_code).
    Keep the rest of the record intact, especially method/status/timing.
    """

    _PREFIX = "/api/tts/"

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = args[2]
        if isinstance(path, str) and path.startswith(self._PREFIX):
            ticket = path[len(self._PREFIX):].split("?", 1)[0]
            if ticket:
                # Omit the query string too; there is no diagnostic benefit
                # in preserving arbitrary parameters on an authenticated URL.
                record.args = (*args[:2], "/api/tts/<redacted>", *args[3:])
        return True


def redact_uvicorn_tts_access_logs(
    *, access_logger: logging.Logger | None = None
) -> None:
    """Filter all access handlers once, even under an existing host config."""
    logger = access_logger if access_logger is not None else logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _TtsTicketAccessLogFilter) for item in logger.filters):
        logger.addFilter(_TtsTicketAccessLogFilter())

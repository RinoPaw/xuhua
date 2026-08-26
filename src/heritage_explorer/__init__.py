"""叙华 heritage conversation service."""

import logging


def _configure_package_logging() -> None:
    """Keep application diagnostics visible without replacing host handlers."""

    logger = logging.getLogger("heritage_explorer")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_package_logging()

__version__ = "0.2.0"

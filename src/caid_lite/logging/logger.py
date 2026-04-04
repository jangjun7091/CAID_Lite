"""Structured console logger backed by the ``rich`` library.

Usage::

    from caid_lite.logging import get_logger
    log = get_logger(__name__)
    log.info("Starting pipeline run", extra={"run_id": run_id})
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from rich.logging import RichHandler as _RichHandler

    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RICH_AVAILABLE = False

_LOG_FORMAT = "%(message)s"
_DATE_FORMAT = "%H:%M:%S"

# Module-level flag so we only call basicConfig once per process.
_configured = False


def _configure(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    if _RICH_AVAILABLE:
        logging.basicConfig(
            level=level,
            format=_LOG_FORMAT,
            datefmt=_DATE_FORMAT,
            handlers=[_RichHandler(rich_tracebacks=True, markup=True)],
        )
    else:  # pragma: no cover
        logging.basicConfig(level=level, format="%(levelname)s %(name)s — %(message)s")

    _configured = True


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """Return a named logger, initialising the root handler on first call.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling module.
        level: Override log level for this logger (e.g. ``"DEBUG"``).
            Defaults to the level set in ``config/default.yaml``.

    Returns:
        Standard :class:`logging.Logger` instance.
    """
    _configure()
    logger = logging.getLogger(name)
    if level is not None:
        logger.setLevel(level.upper())
    return logger

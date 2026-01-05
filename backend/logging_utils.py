"""Logging configuration helpers for OpenKeyFlow."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

logger = logging.getLogger("openkeyflow")
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3

def configure_logging(enabled: bool, log_path: Path) -> logging.Logger:
    """Configure the shared application logger.

    Logging is written to ``log_path`` when enabled; otherwise, handlers are cleared.
    """

    # Remove existing handlers to avoid duplicate logs when settings change at runtime.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not enabled:
        return logger

    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logger


def set_log_path(new_path: Path, *, enabled: Optional[bool] = None) -> None:
    """Update logger output path and optionally toggle logging."""
    current_enabled = bool(enabled if enabled is not None else logger.handlers)
    configure_logging(current_enabled, new_path)
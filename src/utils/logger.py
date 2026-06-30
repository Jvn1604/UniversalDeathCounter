"""
Centralized logging configuration for Universal Death Counter.

Other modules should call ``get_logger(__name__)`` to obtain a logger
instance rather than configuring logging themselves.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from src.utils.constants import LOG_DIR, LOG_FILE

_CONFIGURED: bool = False


def _configure_root_logger() -> None:
    """Configure the root logger once with console + rotating file handlers."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured logger for the given module name.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A ``logging.Logger`` instance writing to console and rotating file.
    """
    _configure_root_logger()
    return logging.getLogger(name)

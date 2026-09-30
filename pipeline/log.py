"""Logging helper. In CI, call sites must log only counts and stage names, never titles, companies, URLs or resume text (see CLAUDE.md)."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from pipeline.settings import is_ci

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "data" / "logs"

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(console)

    if not is_ci():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            LOG_DIR / f"appollo_{date.today():%Y-%m-%d}.log", encoding="utf-8"  # noqa: DTZ011 (local calendar day is intentional)
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(file_handler)

    return logger

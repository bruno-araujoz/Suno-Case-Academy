"""Logging setup shared by the CLI and tests."""

from __future__ import annotations

import logging
import os

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"


def setup_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=(level or os.environ.get("LOG_LEVEL", "INFO")).upper(), format=_FORMAT
    )
    # httpx logs every request at INFO; keep it quiet unless debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"scraper.{name}")

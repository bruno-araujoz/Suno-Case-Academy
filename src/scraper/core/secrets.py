"""Secrets from the environment + .env, never logged or printed.

pydantic-settings reads .env into Settings fields only, not into os.environ, so code that needs
an arbitrary key (LLM providers) reads it here.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def secrets() -> dict[str, str]:
    from dotenv import dotenv_values

    values = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v}
    return {**values, **{k: v for k, v in os.environ.items() if v}}

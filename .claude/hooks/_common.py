"""Utilitários compartilhados pelos hooks do projeto (sem dependências externas)."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def read_event() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))


def rel_path(file_path: str | None) -> str | None:
    if not file_path:
        return None
    try:
        return Path(file_path).resolve().relative_to(PROJECT_DIR.resolve()).as_posix()
    except ValueError:
        return None


def venv_tool(name: str) -> list[str] | None:
    """Prefere o binário do .venv (rápido); cai para `uv run` se o venv não existir."""
    local = PROJECT_DIR / ".venv" / "bin" / name
    if local.exists():
        return [str(local)]
    if shutil.which("uv"):
        return ["uv", "run", "--frozen", name]
    return None

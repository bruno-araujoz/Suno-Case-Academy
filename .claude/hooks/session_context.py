"""SessionStart: injeta branch, plano ativo e estado do Postgres no contexto da sessão."""

from __future__ import annotations

import re
import subprocess

from _common import PROJECT_DIR, emit


def sh(*cmd: str) -> str:
    try:
        return subprocess.run(
            cmd, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


lines = [f"Branch: {sh('git', 'branch', '--show-current') or '?'}"]

plans = sorted((PROJECT_DIR / "docs" / "plans").glob("[0-9]*.md"))
for plan in plans:
    text = plan.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"Status:\s*\**([^*\n]+)", text)
    lines.append(f"Plano {plan.name}: {m.group(1).strip() if m else 'sem status'}")

db = sh("docker", "ps", "--filter", "name=suno-content-db", "--format", "{{.Status}}")
lines.append(f"Postgres (suno-content-db): {db or 'parado — `docker compose up -d db`'}")

emit(
    {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "Estado do projeto:\n- " + "\n- ".join(lines),
        }
    }
)

"""PostToolUse (Edit|Write): formata e corrige lint do arquivo .py recém-editado.

Não bloqueia (a ferramenta já rodou); se sobrar erro de lint, devolve como contexto ao Claude.
"""

from __future__ import annotations

import subprocess

from _common import PROJECT_DIR, emit, read_event, venv_tool

event = read_event()
file_path = (event.get("tool_input") or {}).get("file_path") or ""
ruff = venv_tool("ruff")
if not file_path.endswith(".py") or ruff is None:
    raise SystemExit(0)

run = dict(cwd=PROJECT_DIR, capture_output=True, text=True, timeout=60)
subprocess.run([*ruff, "format", "--quiet", file_path], **run)
check = subprocess.run([*ruff, "check", "--fix", "--quiet", file_path], **run)
if check.returncode != 0 and check.stdout.strip():
    emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"ruff ainda aponta problemas em {file_path}:\n{check.stdout[-2000:]}"
                ),
            }
        }
    )

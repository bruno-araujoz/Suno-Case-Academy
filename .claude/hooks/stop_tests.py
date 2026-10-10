"""Stop: roda a suíte offline quando há .py alterado desde o último verde.

- Sem .py alterado (ou mesmo estado já validado) -> não roda nada.
- Falhou -> exit 2 com o resumo no stderr: o Claude continua e corrige.
- Respeita stop_hook_active para nunca entrar em loop.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys

from _common import PROJECT_DIR, read_event, venv_tool

event = read_event()
if event.get("stop_hook_active"):
    raise SystemExit(0)

status = subprocess.run(
    ["git", "status", "--porcelain", "--untracked-files=all"],
    cwd=PROJECT_DIR,
    capture_output=True,
    text=True,
)
changed = sorted(
    line[3:].strip().split(" -> ")[-1]
    for line in status.stdout.splitlines()
    if line[3:].strip().endswith(".py")
    and not line.startswith(" D")
    and not line[3:].strip().startswith(".claude/")
)
if not changed:
    raise SystemExit(0)

digest = hashlib.sha256()
for rel in changed:
    p = PROJECT_DIR / rel
    digest.update(rel.encode())
    if p.exists():
        digest.update(p.read_bytes())
fingerprint = digest.hexdigest()

state = PROJECT_DIR / ".claude" / ".state" / "last_green"
if state.exists() and state.read_text().strip() == fingerprint:
    raise SystemExit(0)

pytest = venv_tool("pytest")
if pytest is None:
    raise SystemExit(0)

try:
    result = subprocess.run(
        [*pytest, "-m", "not live", "-x", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
except subprocess.TimeoutExpired as exc:
    print(
        "Stop hook: pytest excedeu 300s — verifique testes lentos "
        "ou com rede sem @pytest.mark.live.",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

# 5 = nenhum teste coletado: não é falha.
if result.returncode in (0, 5):
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(fingerprint)
    raise SystemExit(0)

tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-40:])
print(
    f"Testes offline falhando após alterações em {len(changed)} arquivo(s) .py. "
    f"Corrija antes de encerrar (não edite fixtures para passar):\n{tail}",
    file=sys.stderr,
)
raise SystemExit(2)

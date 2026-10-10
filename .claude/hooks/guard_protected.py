"""PreToolUse (Edit|Write): pede confirmação antes de alterar arquivos que são "verdade".

- tests/fixtures/**: respostas reais gravadas das fontes. Editar para fazer um teste passar
  mascara bugs (principalmente nos testes de self-healing).
- schemas/**: schemas CSS versionados do healer; só devem mudar via healer ou de forma consciente.
"""

from __future__ import annotations

from _common import emit, read_event, rel_path

PROTECTED = {
    "tests/fixtures/": "fixtures são respostas reais gravadas; não edite para fazer teste passar "
    "— recapture com /capture-fixture ou corrija o código",
    "schemas/": "schemas versionados do self-healing; devem mudar via healer (nova versão), "
    "não por edição manual",
}

event = read_event()
path = rel_path((event.get("tool_input") or {}).get("file_path"))
if path:
    for prefix, reason in PROTECTED.items():
        if path.startswith(prefix):
            emit(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": f"Arquivo protegido ({path}): {reason}.",
                    }
                }
            )
            break

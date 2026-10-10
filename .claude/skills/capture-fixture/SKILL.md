---
name: capture-fixture
description: Grava a resposta real de uma URL (HTML/JSON/PDF/RSS) em tests/fixtures/<fonte>/ com metadados, para testes offline do scraper. Use ao criar ou atualizar testes de conectores.
arguments: [fonte, url, nome]
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/capture.py *)
---

Capture a fixture da fonte `$fonte` a partir de `$url` (nome do arquivo: `$nome`, opcional).

1. Rode:
   `python3 ${CLAUDE_SKILL_DIR}/scripts/capture.py "$fonte" "$url" $nome`
2. O script salva `tests/fixtures/<fonte>/<nome>.<ext>` + `<nome>.meta.json`
   (url, data UTC, status, content-type, sha256) e recusa sobrescrever sem `--force`.
3. Se for recaptura de uma fixture existente (a fonte mudou), **pergunte antes** de usar
   `--force` e explique a diferença ao usuário — fixtures são a verdade dos testes.
4. Mostre um resumo: tamanho, content-type e os primeiros elementos relevantes
   (ex.: título dos itens) para confirmar que não é página de bloqueio/captcha/cookie wall.

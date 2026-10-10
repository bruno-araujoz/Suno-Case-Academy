---
name: source-health
description: Relatório de saúde das fontes do scraper (ok/degraded/healed/failed), com diagnóstico e próximo passo. Use quando perguntarem se o scraper está funcionando ou por que uma fonte parou.
---

## Saúde atual das fontes
!`test -f scrape.py && uv run python scrape.py --health 2>&1 | tail -60 || echo "scrape.py --health ainda não existe (fase 01 do scraper não implementada)."`

## Instruções
1. Se o comando acima não existir ainda, diga isso e aponte `docs/plans/01-scraper.md` (item
   `source_health`). Não invente números.
2. Para cada fonte que não está `ok`, classifique a causa provável:
   - **degraded** com queda brusca de itens → layout mudou (candidato a healer).
   - **failed** com HTTP 403/429 → bloqueio/rate limit (ajustar politeness, não o parser).
   - **healed** → mostre a versão nova do schema e peça revisão humana do diff em `schemas/`.
3. Termine com uma tabela: fonte | status | causa | próximo passo (comando ou arquivo).

---
name: new-connector
description: Adiciona uma nova fonte ao scraper — entrada em sources.yaml (feeds) ou conector em código (APIs com lógica própria) — com fixture e teste offline.
arguments: [fonte, tipo]
disable-model-invocation: true
---

Nova fonte: `$fonte`, tipo `$tipo` (`feed` | `api`).

## Contexto atual
!`ls docs/sources/ src/scraper/sources/; grep -n "name:" sources.yaml`

## Pré-condição
Sem ficha `docs/sources/$fonte.md` (ou linha em `docs/sources/feeds.md`) com endpoint e campos
**confirmados**, rode antes o agente `source-scout`. Não invente endpoint.

## Tipo `feed` (RSS/Atom/JSON Feed/WordPress) — sem código novo
1. Acrescente em `sources.yaml` → `feeds:` `{name, kind: rss|wpjson, url, homepage, params?}`
   (`homepage` é obrigatório: é dela que o healer L2 redescobre o feed).
2. `/capture-fixture feeds <url>` e um teste em `tests/sources/test_feed.py` só se o formato
   tiver algo novo (datas, conteúdo em outro campo).
3. Linha na tabela de `docs/sources/feeds.md` e no README.

## Tipo `api` — conector em código
1. `/capture-fixture $fonte <url>` (listagem e, se houver, detalhe).
2. `src/scraper/sources/$fonte.py` a partir de `${CLAUDE_SKILL_DIR}/templates/source_api.py.tmpl`.
3. `tests/sources/test_$fonte.py` a partir de `${CLAUDE_SKILL_DIR}/templates/test_source.py.tmpl`.
4. Registre em `Pipeline.build_sources` (`src/scraper/pipeline.py`) e em `sources.yaml` →
   `official: {$fonte: {enabled: true}}`.
5. Ficha `docs/sources/$fonte.md` + linha no README.

## Fim
`uv run pytest -m "not live" -q` verde → `uv run python scrape.py run --dry-run --source $fonte`
→ peça ao `scrape-verifier` para auditar. **Não commite** — resuma os arquivos para o usuário.

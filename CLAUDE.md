# Suno Content — Case Suno Academy × Finance

Pipeline que coleta documentos e notícias do mercado financeiro (scraper self-healing), adapta o
conteúdo para 3 níveis de sofisticação (Iniciante, Intermediário, Avançado) e **prova com métricas
determinísticas** que cada nível foi respeitado. O avaliador é o produto (Eval-Driven Development).

- Escopo, entregáveis e decisões do time: `docs/TAPI.md` — leia antes de decidir escopo.
- Planos por fase (fonte de verdade entre sessões): `docs/plans/NN-<fase>.md`.
- Fichas das fontes de dados: `docs/sources/<fonte>.md`.

## Stack
Python 3.11+ · `uv` · asyncio + httpx · Pydantic v2 · PostgreSQL 16 (Docker) · pytest · ruff ·
LangGraph (grafo) · Crawl4AI/trafilatura (extração) · LLM com fallback
OpenRouter → Groq → Gemini → Ollama.

## Comandos
```bash
uv sync                                   # instala dependências
uv run pytest -m "not live"               # suíte offline (a que o Stop hook roda)
uv run pytest -m live                     # testes contra fontes reais (rede)
uv run ruff check --fix . && uv run ruff format .
docker compose up -d db                   # Postgres local (suno-content-db)
docker compose exec db psql -U postgres -d suno_content
uv run python scrape.py run --dry-run --since 3d   # coleta sem gravar
uv run python scrape.py run                # incremental (grava no Postgres)
uv run python scrape.py health             # saúde por fonte
uv run uvicorn web.app:app --port 8000     # interface → http://localhost:8000
```

## Layout
```
src/scraper/core/       config, http (HTTP/2, limite por host, GET condicional), models (Document), db, robots
src/scraper/sources/    bcb_copom, cvm_ipe, ibge, bcb_sgs, feed (runner genérico), coverage (Google News)
src/scraper/enrich/     pdf (pymupdf), article (trafilatura → Crawl4AI opcional), enricher, pool (CPU)
src/scraper/heal/       health (L0), rediscover (L2), schema (L4 + schemas versionados), healer
src/scraper/relevance/  text, cluster (eventos), scorer, stage (fim da rodada)
src/scraper/pipeline.py streaming: fontes → dedupe → enriquecimento → lote → relevância
sources.yaml            registro de fontes (feed novo = entrada aqui)
glossary/events.yaml    termos de eventos de mercado (relevância)
scrape.py               CLI: run | backfill | refresh | health | heal-demo
src/llm/                LLMRouter (failover, cota por chave, schema estrito), prompts versionados
src/generation/         grafo LangGraph (âncoras → brief → escrita → avaliação → reflexão), service
src/evals/              avaliador híbrido (Flesch-PT, jargão, lastro numérico, juiz), lote/matrizes
src/glossary/           matcher do glossário local (glossary/candidates.yaml)
src/topics/             escolha de tema: busca full-text local + busca WP-JSON nos portais
src/web/                FastAPI (API + SSE) e front estático em static/ (HTML/CSS/JS puro)
generate.py, evaluate.py  CLIs de geração e de avaliação em lote
sql/                    migrations numeradas e idempotentes
schemas/                schemas CSS versionados do healer (protegido por hook)
tests/                  offline; tests/fixtures/ = respostas reais gravadas (protegido por hook)
docs/                   TAPI.md, plans/, sources/
```

## Convenções
- Código, identificadores e docstrings técnicas em **inglês**; docs, planos e commits em **PT-BR**.
- **NUNCA faça `git commit` nem `git push`** (bloqueado no settings). Quem commita é o usuário;
  ao terminar, apenas resuma o que mudou para ele commitar.
- Async em todo I/O. Pydantic nas fronteiras (dado externo entra validado ou não entra).
- Datas sempre timezone-aware (`America/Sao_Paulo` na origem, UTC no banco).
- Configuração via `.env` + `Settings`; nunca hardcode chave. `.env` é ilegível para o Claude.
- Use Context7 para docs de bibliotecas (Crawl4AI, LangGraph, trafilatura, asyncpg, Pydantic).

## Definition of done
1. `uv run pytest -m "not live"` verde (o Stop hook bloqueia o fim do turno se falhar).
2. ruff limpo (o hook de pós-edição formata e reporta).
3. Plano da fase em `docs/plans/` atualizado (checklist marcado) — use `/phase-plan`.
4. Mudança em fonte ao vivo verificada pelo agente `scrape-verifier`.

## Regras de ouro
- Teste offline **nunca** acessa a rede; o que acessa leva `@pytest.mark.live`.
- **Nunca** edite `tests/fixtures/` para fazer um teste passar — corrija o código ou recapture.
- O `HttpClient` nunca deixa exceção de rede vazar: devolve `FetchResult` (status 0 = falha de
  rede; 4xx/5xx com `error`); uma fonte quebrada não derruba as outras.
- LLM é último recurso no scraping (camada 3 / healer), nunca no caminho quente.
- Não invente endpoints ou campos de API: confirme (ficha em `docs/sources/` ou `source-scout`).

## Fluxo por fase
plan mode → `/phase-plan <fase>` → implementar na thread principal → `scrape-verifier` (fontes
ao vivo) → `/code-review` → resumo das mudanças para o usuário commitar.
Novas fontes: `source-scout` → `/new-connector` (ou só uma entrada em `sources.yaml` se for feed).

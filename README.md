# Suno-Case-Academy — Suno Content

Pipeline de IA que coleta documentos e notícias do mercado financeiro, adapta o conteúdo para
3 níveis de sofisticação (Iniciante, Intermediário, Avançado) e mede com métricas
determinísticas se cada nível foi respeitado. Case **Suno × Academy (Finance)**.

- Escopo e decisões: [`docs/TAPI.md`](docs/TAPI.md)
- Planos por fase: [`docs/plans/`](docs/plans/)
- Fichas das fontes: [`docs/sources/`](docs/sources/)

> Status: **scraper (fase 01) implementado**; geração e avaliador são as próximas fases.

## Setup
```bash
uv sync                       # Python 3.12 (fixado em .python-version)
cp .env.example .env          # chaves só são necessárias para o healer L4 (LLM)
docker compose up -d db
uv run pytest -m "not live"   # suíte offline
```
Opcionais: `uv sync --extra browser` (Crawl4AI: fallback de renderização JS e healer L4) e
`--extra embed` (fastembed). No WSL com o repositório em `/mnt/c`, colocar o venv no filesystem
Linux acelera os imports ~3,5× (10 s → 2,8 s): `export UV_PROJECT_ENVIRONMENT=~/.venvs/suno-content`.

## Scraper
```bash
uv run python scrape.py run --dry-run --since 3d    # coleta sem gravar (mostra tabela + amostra)
uv run python scrape.py run                         # incremental, grava no Postgres
uv run python scrape.py run --watch 15m             # contínuo
uv run python scrape.py backfill --source cvm_ipe --year 2025
uv run python scrape.py health                       # saúde por fonte
uv run python scrape.py heal-demo                    # self-healing ao vivo (não grava nada)
```

`heal-demo` quebra fontes reais de propósito e mostra a escada de reparo funcionando:

| Cenário | O que quebra | Reparo esperado |
|---|---|---|
| `404` | URL do feed da Suno trocada por uma inexistente | L2: acha `/noticias/feed/` anunciado na home |
| `stale` | feed real do E-Investidor, parado desde maio/2026 | L2: adota o feed Arc vivo anunciado na home |
| `html` | listagem do Money Times com schema de um layout antigo | L4: gera schema v2 validado (LLM real com o extra `browser` + chave; senão, simulado e avisado) |

Rode um cenário com `--scenario 404`. Para o L4 usar o LLM real: `uv sync --extra browser` e ao
menos uma chave no `.env` (`GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY` ou
`OPENROUTER_API_KEY_1/2`); a cadeia tenta na ordem e pula provedores sem chave. A versão automatizada é `uv run pytest -m live tests/heal/test_demo_live.py`.

Arquitetura (detalhes e decisões: [`docs/plans/01-scraper.md`](docs/plans/01-scraper.md)):
```
sources.yaml → fontes async (GET condicional, watermark) → contrato Pydantic → dedupe
  → enriquecimento só se faltar texto (PDF/pymupdf, trafilatura, Crawl4AI opcional)
  → gravação em lote → relevância (eventos agrupados + cobertura + recência)
self-healing por fonte: L0 detecta → L2 redescobre o feed (sem LLM) → L4 LLM gera schema CSS validado
```

Medido em 2026-10-09 (WSL, repositório em `/mnt/c`):

| Cenário | Resultado |
|---|---|
| Primeira carga, 90 dias | 3.193 documentos em 97 s de pipeline (InfoMoney: 2.000 posts = 91 s) |
| Rodada incremental | 7–20 s (304/"nada novo" na maioria das fontes); 0 chamadas de LLM |
| Self-healing real | E-Investidor: feed parado desde maio → L2 achou o feed vivo anunciado na home |
| Relevância | IPCA de setembro agrupado com 39 veículos; recorde do Ibovespa com 25 |

## Fontes de dados
| Fonte | Tipo | Camada | Onde | Ficha |
|---|---|---|---|---|
| BCB Copom (atas, comunicados) | oficial | API JSON (texto completo) | `sources/bcb_copom.py` | [ficha](docs/sources/bcb_copom.md) |
| CVM IPE (fatos relevantes, releases) | oficial | ZIP dados abertos + PDF | `sources/cvm_ipe.py` | [ficha](docs/sources/cvm_ipe.md) |
| IBGE (releases de indicadores) | oficial | API (resumo; página bloqueia) | `sources/ibge.py` | [ficha](docs/sources/ibge.md) |
| BCB SGS (Selic, IPCA, câmbio, CDI) | oficial | API → `market_series` | `sources/bcb_sgs.py` | [ficha](docs/sources/bcb_sgs.md) |
| 10 portais (Suno, InfoMoney, Valor, Money Times, Exame, Estadão, E-Investidor, Seu Dinheiro, Brazil Journal, Bloomberg Línea) | notícia | RSS / WP-JSON | `sources.yaml` | [ficha](docs/sources/feeds.md) |
| Google News | cobertura | RSS de busca (só manchetes) | `sources/coverage.py` | [ficha](docs/sources/google_news.md) |

Limitações conhecidas: PDFs escaneados da CVM não têm texto (OCR fora do escopo); páginas da
Agência IBGE bloqueiam clientes automatizados (usamos o resumo oficial da API); o healer L4
precisa do extra `browser` e de uma chave de LLM.

## Desenvolvimento com Claude Code
O repositório traz um harness versionado em `.claude/` (compartilhado pelo time):

| Peça | O que faz |
|---|---|
| `CLAUDE.md` | contexto, comandos, convenções e definition of done |
| `.claude/rules/` | regras carregadas só ao tocar `src/scraper/`, `tests/` ou `sql/` |
| Hook `PostToolUse` | `ruff format` + `ruff check --fix` em todo `.py` editado |
| Hook `PreToolUse` | pede confirmação antes de alterar `tests/fixtures/` e `schemas/` |
| Hook `Stop` | roda `pytest -m "not live"` se houver `.py` alterado; falhou → o Claude continua |
| Hook `SessionStart` | injeta branch, status dos planos e estado do Postgres |
| `/new-connector` | cria conector + fixture + teste no padrão do projeto |
| `/capture-fixture` | grava resposta real de uma fonte em `tests/fixtures/` |
| `/source-health` | diagnóstico das fontes via `scrape.py health` |
| `/phase-plan` | cria/atualiza o plano da fase em `docs/plans/` |
| agente `source-scout` | investiga uma fonte e escreve `docs/sources/<fonte>.md` |
| agente `scrape-verifier` | audita de forma independente a saída do scraper ao vivo |

Notas pessoais: crie `CLAUDE.local.md` (ignorado pelo git).

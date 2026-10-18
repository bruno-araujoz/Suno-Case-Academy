# Suno-Case-Academy — Suno Content

Pipeline de IA que coleta documentos e notícias do mercado financeiro, adapta o conteúdo para
3 níveis de sofisticação (Iniciante, Intermediário, Avançado) e mede com métricas
determinísticas se cada nível foi respeitado. Case **Suno × Academy (Finance)**.

- Escopo e decisões: [`docs/TAPI.md`](docs/TAPI.md)
- Planos por fase: [`docs/plans/`](docs/plans/)
- Fichas das fontes: [`docs/sources/`](docs/sources/)

> Status: **fase 01 (scraper) e fase 02 (geração, avaliador, UI MVP) implementadas**.

## Setup
```bash
bash scripts/bootstrap.sh     # tudo de uma vez: uv sync, .env, Postgres, histórico do Copom,
                              # coleta inicial e testes (~2 min; testado num banco vazio)
```
Passo a passo manual: `uv sync` → `cp .env.example .env` → `docker compose up -d db` →
`uv run python scrape.py refresh` → `uv run pytest`. Para gerar conteúdo, preencha ao menos uma
chave de LLM no `.env` (`GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY`...).

Alternativa em container (UI + banco): `docker compose --profile app up -d --build` →
http://localhost:8001.

**Documentos da entrega:** [relatório experimental](docs/RELATORIO.md) ·
[roteiro e checklist do vídeo](docs/VIDEO.md) · [escopo e decisões](docs/TAPI.md).
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

## Geração e avaliação
```bash
uv run uvicorn web.app:app --port 8000                          # interface → http://localhost:8000
uv run python generate.py --format carrossel --level iniciante   # CLI
uv run python generate.py --list-events                          # eventos em destaque
uv run python evaluate.py batch --events 3 --judge               # lote + matrizes de confusão
uv run python generate.py --level iniciante --demo-reflection --force   # demo do reflection loop
```

Fluxo de um pedido (formato + nível escolhidos pelo usuário; detalhes em
[`docs/plans/02-geracao-avaliacao.md`](docs/plans/02-geracao-avaliacao.md)):

```
atualiza fontes vencidas (≤20 s) → evento mais relevante → âncoras [LLM, verificadas por código, cache]
→ instruções do nível [glossário] → escrita [LLM] → avaliação [métricas determinísticas]
→ reprovou? reescreve com o relatório numérico (≤3 tentativas) → conteúdo + métricas + fontes
```

| Métrica (determinística) | Como | Por quê |
|---|---|---|
| Legibilidade | Flesch adaptado ao PT-BR (Martins, 1996) + sílabas `pyphen` | `textstat` (pt) erra; metas calibradas no corpus (atas ~31, notícias ~45) |
| Jargão sem explicação | glossário em camadas + marcadores de aposto/explicação | iniciante não pode ter termo técnico "solto" |
| Densidade técnica | termos intermediários+avançados /100 palavras | avançado não pode ser infantilizado (atas ~3, notícias ~0,6) |
| Números sem lastro | todo número precisa existir nas âncoras verificadas | falha dura: zera o score |
| Cobertura de fatos | fatos centrais presentes | impede "resumo por encurtamento" |
| Regras do formato | slides, ≤60 s/150 palavras, linha do tempo | estrutura do TAPI |
| Juiz LLM (opcional) | veredito por afirmação SEM número, contra as âncoras | só onde o código não alcança |

- **Glossário** (`glossary/`): 244 termos (BCB + mineração do corpus + semente manual), propostos
  por LLM e **pendentes de revisão do time** — `scripts/build_glossary.py promote` após revisar.
- **Metas por nível/formato**: `config/levels.yaml` (calibradas; recalibrar com `scripts/calibrate.py`).
- **LLM**: cadeia Groq ×2 → Gemini (3.5-flash, 3.5-flash-lite, 2.5-flash), saída JSON estrita,
  failover e espera de cota; toda chamada registrada em `llm_calls`.

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

# Plano 01 — Scraper self-healing de mercado financeiro (v2)

> Status: **concluído** · atualizado em 2026-10-09

## Contexto
O harness já está pronto. O plano v1 do scraper (`Suno-Case-Academy/docs/plans/01-scraper.md`)
foi escrito antes de testar as fontes de verdade. Este v2 nasceu de uma **pesquisa ao vivo das
fontes (2026-10-09)** e de **benchmarks com dados reais**, e reavalia o v1 para chegar a um
scraper mais simples, mais rápido e mais robusto.

**Nova regra do usuário: NUNCA commitar.** O harness hoje libera `git commit` e o CLAUDE.md fala
em commits, então isso será corrigido no passo 0.

---

## 1. O que a pesquisa revelou (e mudou o plano)
| Descoberta (verificada com curl) | Impacto |
|---|---|
| **BCB Copom**: `GET /api/servico/sitebcb/copom/atas?quantidade=N` → `atas_detalhes?nro_reuniao=281` devolve **`textoAta` (HTML completo)** + `urlPdfAta`. Mesmo padrão em `comunicados` e `comunicados_detalhes` (`textoComunicado`) | a ata chega como texto completo via API JSON, **sem parse de PDF** |
| A API do BCB usa `nroReuniao` em uma rota e `nro_reuniao` em outra | confirma o valor da tolerância a múltiplas chaves (`first(raw, KEYS)`) |
| **CVM IPE** (`dados.cvm.gov.br/.../IPE/DADOS/ipe_cia_aberta_2026.zip`, 2 MB, ETag) tem **1.953 Fatos Relevantes e 1.221 Press-releases (releases de resultados)** só em 2026, cada um com `Link_Download` | resolve **fatos relevantes e releases da B3 com uma fonte só**. Sai do plano raspar sites de RI, que era a fonte mais frágil do v1 |
| O link da CVM entrega um PDF com `Content-Type: text/html` | detectar o tipo pelos bytes (`%PDF`), nunca pelo header |
| **8 portais com feed e texto completo** (`content:encoded` ou WP-JSON `content`): Suno, InfoMoney (WP-JSON, categoria Mercados id=1), Money Times, Exame, Estadão Economia, E-Investidor, Seu Dinheiro, Brazil Journal, Bloomberg Línea | **a maioria das notícias não precisa de deep fetch**: o texto vem no feed |
| Valor RSS (100 itens, sem conteúdo, paywall) e Google News RSS por busca (`news.google.com/rss/search?q=...&hl=pt-BR`) | servem como **sinal de cobertura** (relevância), não como conteúdo |
| BCB SGS (`api.bcb.gov.br/dados/serie/bcdata.sgs.432/...`) e IBGE (`servicodados.ibge.gov.br/api/v3/noticias`) respondem rápido em JSON | séries para a checagem de fatos no futuro e releases de IPCA/PIB |
| Os feeds mandam `ETag`/`Last-Modified` | GET condicional: rodada sem novidade ≈ uma série de respostas 304 |

**Benchmark com os dados reais** (feed Bloomberg Línea de 1 MB/100 itens, artigo Money Times,
release de 28 páginas):

| Tarefa | Opção lenta | Opção escolhida |
|---|---|---|
| Parse de feed | feedparser 262 ms | **fastfeedparser 2,7 ms (~100×)** |
| Limpeza de HTML | BeautifulSoup+lxml 17 ms | **selectolax/lexbor 0,5 ms (~35×)** |
| Texto principal | — | trafilatura 24 ms (só quando o feed vier truncado) |
| PDF de 28 páginas | — | **pymupdf 52 ms** |

O fastfeedparser já entrega `content` e `published` com timezone (verificado).

## 2. Reavaliação do v1 → decisões do v2
| v1 | Problema | v2 |
|---|---|---|
| Descobrir, depois extrair em duas fases separadas, com fila no Postgres (SKIP LOCKED), como na Nvidia | latência e complexidade desnecessárias; 90% do conteúdo já vem na descoberta | **pipeline em streaming num processo só** (filas asyncio limitadas): coleta → normaliza → dedupe → enriquece só se faltar texto → grava em lote |
| Um conector em código por fonte | 9 portais são o mesmo padrão RSS/WP-JSON | **registro declarativo `sources.yaml`** + 1 runner genérico de feed; conector em código só para fontes com lógica própria (BCB, CVM, IBGE, SGS) |
| Raspar sites de RI da B3 | frágil, cada empresa é diferente | **CVM IPE** cobre releases e fatos relevantes |
| Self-healing = LLM regenera seletores CSS | caro; quase nenhuma fonte usa listagem HTML | **escada de reparo**, com o LLM só no último degrau (ver §4) |
| Relevância com SBERT (torch, ~2 GB) | dependência pesada e lenta para subir | **relevância determinística** (glossário ponderado + tier da fonte + cobertura cruzada + recência); `fastembed` (ONNX, leve) fica como extra opcional |
| Jitter global + semáforo | trata todos os hosts igual | **rate limit por host** (`aiolimiter`) + um único `httpx.AsyncClient` com HTTP/2 e keep-alive |
| `utcnow`/datas ingênuas | ruim para notícia | `TIMESTAMPTZ` e validação de plausibilidade da data |
| PDF/trafilatura no event loop | trabalho de CPU trava o I/O | `ProcessPoolExecutor` (2 workers) para pymupdf e trafilatura |
| APIs de notícias pagas (NewsAPI etc.) | os feeds já cobrem com texto completo e sem custo | **fora do núcleo**; a interface `NewsProvider` fica pronta caso você ache uma API que agregue algo |

**Metas de desempenho:**
- rodada incremental sem novidade em **menos de 30 s** (quase tudo responde 304);
- primeira carga de 90 dias em **menos de 5 min**;
- **zero chamadas de LLM** no caminho feliz.

## 3. Arquitetura v2
```
sources.yaml ─► Source runners (async, 1 por fonte; GET condicional; watermark por fonte)
   │   bcb_copom · cvm_ipe · ibge · bcb_sgs · feed(9 portais) · coverage(Google News, Valor)
   ▼  asyncio.Queue (limitada → backpressure)
Normalizer (Pydantic Document; datas tz-aware; URL canônica) ─► Contract check → source_health
   ▼
Dedupe gate: url_hash (set pré-carregado do banco) + content_hash (xxhash)
   ▼
Enricher (só se preciso): PDF → pymupdf | feed truncado → trafilatura → [extra] Crawl4AI
   ▼                         (CPU-bound em ProcessPool)
Clustering (MinHash LSH título+lead) + Relevance scorer determinístico
   ▼
Batch writer (executemany UPSERT a cada 200 itens ou 2 s) ─► PostgreSQL
```
Itens que falharem no enriquecimento ficam com `status=pending_enrich` e voltam para a fila na
próxima rodada (retomável sem precisar de fila no banco).

## 4. Self-healing v2: uma escada de reparo por fonte
Cada rodada mede a saúde da fonte em relação à média móvel dela em `source_health`: número de
itens, % com texto, % de datas válidas e HTTP. Quando uma métrica cai fora da faixa, a fonte sobe
de degrau:

| Degrau | Mecanismo | Custo |
|---|---|---|
| L0 | contrato Pydantic + métricas de saúde (detecta a quebra) | ~0 |
| L1 | tolerância de formato: múltiplas chaves (`first`/`iter_items`), parser que aceita RSS, Atom e JSON Feed | ~0 |
| L2 | **redescoberta do endpoint sem LLM**: `<link rel="alternate">` na home, `/feed`, `/wp-json/wp/v2/posts`, sitemap de notícias; o endpoint novo é validado pelo contrato e salvo em `source_state` (versionado) | poucos GETs |
| L3 | fallback de conteúdo por item: trafilatura → Crawl4AI (extra opcional, timeout de 30 s) | médio |
| L4 | **LLM**: o `generate_schema` do Crawl4AI gera seletores CSS para uma listagem HTML; valida contra o contrato e salva `schemas/<fonte>.vN.json` | 1 chamada de LLM, uma vez |

Status registrado: `ok | degraded | healed(L2/L4) | failed`, com o motivo. Para a banca, dois
testes com fixture demonstram isso:
- (a) a URL do feed passa a dar 404 e o L2 redescobre o endpoint;
- (b) o layout HTML muda e o L4 gera o schema v2 (com o LLM mockado).

## 5. Relevância (determinística e barata)
`score = 0,35·léxico + 0,25·tier + 0,25·cobertura + 0,15·recência`
- **Léxico**: glossário de eventos de mercado com pesos (decisão de juros, guidance, resultado
  trimestral, M&A, dividendos, rating, fato relevante, IPCA…). Fica em `glossary/` e será
  reaproveitado pelo avaliador do TAPI.
- **Tier**: oficial = 1,0; portal com texto = 0,6; sinal de cobertura = 0.
- **Cobertura**: número de publishers diferentes no mesmo cluster (MinHash LSH; os títulos do
  Google News e do Valor casam por `rapidfuzz`).
- **Recência**: decaimento exponencial com meia-vida de 48 h.

Os pesos ficam em `config`. Score ≥ limiar → `high_priority`, o que define a prioridade para o
grafo do TAPI.

## 6. Modelo de dados (`sql/001…004`)
- `documents`:
  - identificação: `id`, `url_hash UNIQUE`, `url`, `source`, `tier`, `doc_type`
    (copom_ata | copom_comunicado | fato_relevante | press_release | ibge_release | news);
  - conteúdo: `title`, `published_at TIMESTAMPTZ`, `author`, `content_text`, `content_hash`,
    `pdf_url`;
  - processamento: `extraction_level`, `cluster_id`, `relevance_score`, `status`;
  - extras: `meta JSONB`, `collected_at`.
- `coverage_signals`: cluster_id, publisher, title, url, seen_at.
- `source_state`: source, endpoint, etag, last_modified, watermark, schema_version, updated_at.
- `source_health`: run_id, source, items_seen, items_new, valid_ratio, level, status, error,
  duration_ms, run_at.
- `market_series`: series_code, ref_date, value (SGS), para a checagem de fatos futura.

## 7. Layout e dependências
```
src/scraper/
  core/        config.py · http.py (client HTTP/2, limiter por host, GET condicional, nunca lança)
               models.py (Document, NewsItem) · db.py (pool, migrations, upsert em lote) · logging.py
  sources/     registry.py (lê sources.yaml) · feed.py (runner genérico RSS/WP-JSON)
               bcb_copom.py · cvm_ipe.py · ibge.py · bcb_sgs.py · coverage.py
  enrich/      pdf.py · article.py (trafilatura → crawl4ai) · pool.py (ProcessPool)
  heal/        health.py (L0) · rediscover.py (L2) · schema_gen.py (L4)
  relevance/   cluster.py (MinHash) · scorer.py
  pipeline.py  (filas, workers, batch writer)
sources.yaml · glossary/events.yaml · schemas/ · sql/ · scrape.py (CLI)
```
- **Dependências do núcleo**: httpx[http2], aiolimiter, pydantic, pydantic-settings, asyncpg,
  fastfeedparser, selectolax, trafilatura, pymupdf, datasketch, rapidfuzz, xxhash, pyyaml,
  tenacity.
- **Extras opcionais**: `browser` (crawl4ai, que já traz o LLM via litellm) e `embed` (fastembed).
- **Python 3.12** fixado com `uv python pin` (o sistema tem 3.14, e as wheels de
  pymupdf/selectolax/crawl4ai são mais garantidas no 3.12).

**CLI:**
- `scrape.py run [--source X] [--since 90d] [--dry-run] [--no-enrich] [--watch 15m]`
- `scrape.py health`
- `scrape.py backfill --source cvm_ipe --year 2025`

## 8. Ordem de implementação (cada passo testável sozinho, **sem commits**)
0. **Ajustar o harness à regra "nunca commitar"** e salvar a memória:
   - `settings.json`: tirar `git add`/`git commit` do allow e pôr `Bash(git commit*)` e
     `Bash(git push*)` no deny;
   - CLAUDE.md: trocar a convenção de commits por "nunca commitar, o usuário commita";
   - `/new-connector`: tirar o passo de commit e trocar o template RSS por uma entrada no
     `sources.yaml`;
   - `/phase-plan`: tirar o "~1 commit";
   - README.
   - Gravar em `docs/plans/01-scraper.md` este v2, substituindo o v1, com uma nota sobre o que mudou.
1. **Core** (config, http, models, db, migrations) + testes do http (304, limite por host, nunca
   lança).
2. **bcb_copom + bcb_sgs**: ganho rápido; valida o contrato fim a fim com documentos oficiais.
3. **Runner de feed genérico + `sources.yaml`** com os 9 portais (fixtures gravadas com
   `/capture-fixture`).
4. **cvm_ipe**: ZIP com ETag, filtro (Fato Relevante e Press-release, a partir de `--since`),
   download com detecção por bytes, pymupdf no ProcessPool.
5. **Pipeline em streaming** + dedupe + batch writer + `source_state`/`source_health` + CLI.
6. **Enricher** (trafilatura e o extra Crawl4AI) para itens truncados.
7. **Self-healing L2 e L4** + os dois testes de demonstração.
8. **Cobertura** (Google News, Valor) + clustering + relevância.
9. **ibge** + fichas em `docs/sources/` (via `source-scout`) + README com a tabela de fontes.

## Verificação
- `uv run pytest -m "not live"`: core, cada fonte com fixture, dedupe, cluster e os dois cenários
  de self-healing, todos verdes.
- `uv run python scrape.py run --dry-run --since 30d`: lista documentos de todas as fontes com
  `published_at` em timezone e `extraction_level`. O `scrape-verifier` aprova cada fonte.
- **Desempenho**: rodar `scrape.py run` duas vezes seguidas. A segunda deve mostrar ~100% de
  respostas 304, 0 itens novos e menos de 30 s. A primeira carga de 90 dias deve ficar em menos de
  5 min. Os tempos ficam no `source_health.duration_ms`.
- `scrape.py health` mostra status por fonte. Os testes provam `healed(L2)` e `healed(L4)`.
- Contagem no banco: as atas do Copom das últimas reuniões (até a 281ª) e os fatos
  relevantes/releases da CVM do período, sem duplicatas (`url_hash` único).

## Checklist
- [x] 0. Harness ajustado à regra "nunca commitar"; plano v2 gravado
- [x] 1. Core (config, http, models, db, migrations) + testes
- [x] 2. bcb_copom + bcb_sgs
- [x] 3. Runner de feed genérico + sources.yaml (9 portais)
- [x] 4. cvm_ipe (ZIP + PDF)
- [x] 5. Pipeline streaming + dedupe + batch writer + state/health + CLI
- [x] 6. Enricher (trafilatura / Crawl4AI extra)
- [x] 7. Self-healing L2 + L4 + testes de demonstração
- [x] 8. Cobertura + clustering + relevância
- [x] 9. ibge + fichas docs/sources + README

## Log
- 2026-10-09 (implementação — desvios do plano, todos medidos em dados reais):
  - **Valor** promovido de "cobertura" a fonte: o `description` do RSS traz texto (mediana 2,3 mil
    caracteres, 80% ≥ 1.000). Cobertura ficou só com Google News.
  - **Clustering**: MinHash LSH + union-find (v2 original) encadeou eventos num cluster de 110
    veículos e o `datasketch` puxava scipy (17 s de import no /mnt/c). Trocado por índice
    invertido + atribuição ao cluster do membro mais parecido (Jaccard ≥ 0,35, ou ≥ 0,15 com
    ticker), com números ("0,82%") como tokens. Resultado: IPCA 0,82% = 1 cluster de 40
    veículos, recorde do Ibovespa = 24, sem clusters misturados.
  - **Relevância no fim da rodada** (não por lote), para cada documento ver a cobertura completa.
  - **Self-healing**: caso real — E-Investidor `/feed/` parado desde 2026-05-27; L0 detecta
    "feed parado" (item mais novo > `stale_feed_days`), L2 adota o feed Arc anunciado na home.
    Bug encontrado na rodada real e corrigido com teste de regressão: WP-JSON incremental vazio
    era lido como "feed sem entradas" e trocava o InfoMoney para o RSS genérico.
  - **L4** implementado com schema no formato do Crawl4AI aplicado via selectolax (sem browser);
    gerador = `generate_schema` do Crawl4AI com a cadeia de LLM; testado com LLM mockado.
  - **IBGE**: página completa responde 403 (WAF) → não contornado; usa o resumo da API.
  - **SGS**: 404 = janela sem valor novo (séries mensais), não falha.
  - **trafilatura**: busca de data extensa levava ~9,5 s em páginas sem data → só pedimos data
    quando ela é provisória e com `extensive_search=False` (6 ms).
  - CVM: limite de PDFs vazava sob concorrência (reserva de vaga antes do await).
  - **Auditoria independente** (dry-run ao vivo, 15 fontes, números conferidos com curl):
    reprovou a Exame — 18/25 itens eram só teaser ("Leia mais em: URL") e passavam como prontos
    porque o rodapé inflava o tamanho. Corrigido: `clean_feed_text` remove boilerplate e marca
    teasers para enriquecimento (Exame: mediana 4,4 mil caracteres via artigo). Também: rodapé
    "The post … appeared first on" removido; SGS usa a data de São Paulo no fim da janela.
  - **L4 com LLM real validado (2026-10-14)**: modelos padrão estavam descontinuados
    (`llama-3.3-70b-versatile` no Groq, `gemini-2.0-flash`) → trocados por `openai/gpt-oss-120b`
    e `gemini-2.5-flash` (checados na API dos provedores). Chaves agora lidas do `.env` (antes só de
    `os.environ`, que o pydantic-settings não preenche). HTML enviado ao LLM reduzido de ~99 mil
    para ~12 mil caracteres (limite gratuito do Groq: 8k tokens/min); falha de uma chave cai
    para a próxima (Groq 1 → Groq 2 → Gemini). Crawl4AI (extra `browser`) instalado e testado.
  - Pendências conhecidas: e-mail do autor/"IM Trader" no fim de textos do InfoMoney (ruído
    menor); OCR para PDFs escaneados da CVM; o agente `scrape-verifier` só carrega em sessões
    abertas dentro do repositório.
- 2026-10-09: v1 (descoberta→extração em 2 fases, RI da B3, SBERT, LLM-healer central) substituído
  pelo v2 após pesquisa ao vivo das fontes e benchmark (ver §1–§2). Regra nova: nunca commitar.

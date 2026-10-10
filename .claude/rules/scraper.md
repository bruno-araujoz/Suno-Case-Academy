---
paths:
  - "src/scraper/**"
  - "scrape.py"
  - "sources.yaml"
---

# Regras do scraper (arquitetura v2 — ver docs/plans/01-scraper.md)

- **Feed novo = entrada em `sources.yaml`**, não código. Código só para fontes com lógica própria
  (`src/scraper/sources/{bcb_copom,cvm_ipe,ibge,bcb_sgs}.py`), herdando `Source` e implementando
  `async _collect() -> AsyncIterator[Document]`; registre em `Pipeline.build_sources`.
- HTTP só via `HttpClient` (`core/http.py`): HTTP/2, limite por host, GET condicional, nunca
  lança (status 0 = falha de rede). Nunca `httpx.AsyncClient` cru. Páginas (artigos, homes,
  listagens) passam por `RobotsCache`; feeds/APIs documentadas não.
- Todo item vira `Document` via `Source.build()` (contrato Pydantic: URL canônica, data tz-aware
  e plausível). Inválido é contado em `items_invalid`, nunca derruba a fonte.
- `report.items_seen` = entradas lidas da fonte (saúde), inclusive já conhecidas; incremental
  "nada novo" (304 / WP `after=` vazio) é normal — o L0 usa `newest_entry_at`, não contagem.
- Tolerância a schema: `first(item, KEYS)` / `iter_items(payload)`; URLs/KEYS no topo do módulo.
- Pule detalhes já conhecidos com `self.is_known(url)` antes de requisições caras.
- Trabalho de CPU (PDF, trafilatura) só via `CpuPool`; nada pesado no event loop.
- Self-healing = escada: L0 `heal/health.py` → L2 `heal/rediscover.py` (sem LLM) → L4
  `heal/schema.py` (LLM gera schema CSS, validado por `listing_is_healthy`, salvo como nova
  versão em `schemas/`). Nunca grave schema sem validar; nunca sobrescreva versão existente.
- LLM nunca no caminho feliz. Não contorne bloqueios (403/WAF/paywall): registre na ficha.
- Datas: `parse_datetime` (ingênua = America/Sao_Paulo); WordPress `date_gmt` é UTC.
- Imports pesados (trafilatura, pymupdf, crawl4ai) dentro das funções que os usam: o
  `/mnt/c` torna cada import caro.

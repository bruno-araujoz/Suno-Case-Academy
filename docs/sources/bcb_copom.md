# BCB — Copom (atas e comunicados)
- Tipo: official · Camada: api · Conector: `src/scraper/sources/bcb_copom.py`
- Endpoints (JSON, sem chave):
  - `GET https://www.bcb.gov.br/api/servico/sitebcb/copom/atas?quantidade=N` → `{"conteudo":[{nroReuniao, dataReferencia, dataPublicacao, titulo}]}`
  - `GET .../copom/atas_detalhes?nro_reuniao=281` → `textoAta` (HTML completo), `urlPdfAta`
  - `GET .../copom/comunicados?quantidade=N` / `comunicados_detalhes?nro_reuniao=281` → `textoComunicado`
- Autenticação/limites: nenhuma; sem ETag (HEAD não suportado). Incremental pelo `url_hash` já conhecido: rodada sem novidade = 2 chamadas de listagem.
- Histórico: desde a 82ª reunião (mar/2003).
- Campos: `nroReuniao` (atas) vs `nro_reuniao` (comunicados) — **drift de chave entre rotas**, tratado com `first(..., MEETING_KEYS)`.
- Datas: `AAAA-MM-DD` sem hora (assumido America/Sao_Paulo).
- Fragilidades: API interna do site (não documentada); se mudar, cai para `urlPdfAta` + pymupdf.
- Relevância para o TAPI: insumo central (atas do Copom = documento-alvo do case).
- **Incidente 2026-10-17:** toda a API `api/servico/sitebcb/*` (inclusive o glossário) passou a
  responder `400 Requisição Inválida` com qualquer cabeçalho, embora a documentação de dados
  abertos ainda liste as mesmas URLs; o SGS (`api.bcb.gov.br`), a página pública e os PDFs das atas
  (`/content/copom/atascopom/...pdf`) seguiram funcionando. O scraper marca a fonte como `failed`
  e segue com as demais; o banco mantém o histórico já coletado (86 atas, 2016→2026).
  Não há fallback automático: sem a API não há listagem descobrível dos PDFs (a página é SPA).
- Verificado em: 2026-10-09 (reverificado em 2026-10-17)

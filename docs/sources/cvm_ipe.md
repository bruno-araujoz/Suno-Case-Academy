# CVM — IPE (fatos relevantes e releases de resultados)
- Tipo: official · Camada: api (dados abertos) + pdf · Conector: `src/scraper/sources/cvm_ipe.py`
- Endpoint: `GET https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{ano}.zip` (~2 MB, CSV latin-1, `;`), **com ETag/Last-Modified** (atualização diária).
- Colunas usadas: Nome_Companhia, CNPJ_Companhia, Codigo_CVM, Data_Referencia, Categoria, Tipo, Assunto, Data_Entrega, Protocolo_Entrega, Versao, Link_Download.
- Filtro: `Categoria = Fato Relevante` ou `Tipo = Press-release` (releases de resultados, dentro de "Dados Econômico-Financeiros"); última `Versao` por protocolo. Em 2026 (até out): 1.953 FR + 1.221 press-releases.
- Documento: `Link_Download` (rad.cvm.gov.br) entrega PDF **com `Content-Type: text/html`** → tipo detectado pelos bytes `%PDF-`.
- Custo: PDFs ~0,1–1,6 MB; limite `max_pdfs_per_run` (150) e backlog `pending_enrich` drenado nas rodadas seguintes. PDFs escaneados (sem texto) viram `failed` após 3 tentativas (OCR fora do escopo).
- Substitui: raspagem de sites de RI da B3 (plano v1).
- Verificado em: 2026-10-09

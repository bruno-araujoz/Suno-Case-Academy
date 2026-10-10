# BCB — SGS (séries temporais)
- Tipo: official · Camada: api · Módulo: `src/scraper/sources/bcb_sgs.py` → tabela `market_series`
- Endpoint: `GET https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados?formato=json&dataInicial=dd/mm/aaaa&dataFinal=dd/mm/aaaa`
- Séries: 432 Selic meta · 433 IPCA mensal · 13522 IPCA 12m · 1 dólar venda · 12 CDI diário
- Comportamento: **404 quando a janela não tem valor novo** (séries mensais) → tratado como "sem dados".
- Incremental: a partir da última `ref_date` gravada por série.
- Uso: gabarito numérico para o Factuality Checker do avaliador (fase futura).
- Verificado em: 2026-10-09

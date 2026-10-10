# IBGE — releases (IPCA, PIB, PNAD, indústria, varejo, serviços)
- Tipo: official · Camada: api · Conector: `src/scraper/sources/ibge.py`
- Endpoint: `GET https://servicodados.ibge.gov.br/api/v3/noticias/?tipo=release&de=MM-DD-AAAA&qtd=100&page=N`
- Campos: id, tipo, titulo, introducao (~256 caracteres), data_publicacao (`dd/mm/aaaa HH:MM:SS`), produto_id, link.
- **Página completa bloqueada**: `agenciadenoticias.ibge.gov.br` responde 403 a clientes automatizados (WAF), mesmo com UA de navegador. Não contornamos: o documento guarda o resumo oficial (`no_enrich`), e os números vêm do BCB SGS.
- Filtro: palavras-chave de indicadores de mercado no título (IPCA, PIB, PNAD, indústria, varejo, serviços...).
- Verificado em: 2026-10-09

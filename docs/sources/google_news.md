# Google News — sinal de cobertura
- Tipo: coverage (só manchetes) · Módulo: `src/scraper/sources/coverage.py`
- Endpoint: `GET https://news.google.com/rss/search?q=<consulta> when:3d&hl=pt-BR&gl=BR&ceid=BR:pt-419`
- Publisher: sufixo do título ("… - CNN Brasil"); o fastfeedparser não expõe `<source>`.
- Links são redirecionadores opacos (`news.google.com/rss/articles/...`): usados só como id; **nunca** buscamos o artigo por aqui.
- Uso: contar veículos distintos por evento (cluster) no score de relevância. Não vira documento.
- Termos: o feed declara uso para renderização de manchetes; usamos apenas título/veículo/data como sinal agregado.
- Verificado em: 2026-10-09

# Portais de notícias (feeds) — registro em `sources.yaml`
Um único runner (`src/scraper/sources/feed.py`) atende todos; adicionar um portal = uma entrada no YAML.

| Fonte | Tipo | Endpoint | Texto no feed | Observações |
|---|---|---|---|---|
| suno | rss | suno.com.br/noticias/feed/ | `content:encoded` | ETag |
| infomoney | wpjson | infomoney.com.br/wp-json/wp/v2/posts?categories=1 | `content` | `after=` + paginação (máx. 100/página); 1 = Mercados |
| moneytimes | rss | moneytimes.com.br/feed/ | `content:encoded` | ETag; `?paged=N` |
| exame | rss | exame.com/feed/ | `content:encoded` | |
| estadao_economia | rss (Arc) | estadao.com.br/arc/outboundfeeds/feeds/rss/sections/economia/ | `content:encoded` | |
| einvestidor | rss | einvestidor.estadao.com.br/feed/ | — | **feed parado desde 2026-05-27**; o healer (L2) migra para o feed Arc anunciado na home |
| seudinheiro | rss | seudinheiro.com/feed/ | `content:encoded` | |
| braziljournal | rss | braziljournal.com/feed/ | `content:encoded` | |
| valor | rss | valor.globo.com/rss/valor/ | `description` (mediana 2,3 mil caracteres) | promovido de "cobertura" para fonte |
| bloomberglinea | rss (Arc) | bloomberglinea.com.br/arc/outboundfeeds/rss/?outputType=xml | `content:encoded` | 100 itens, ~1 MB |

- Datas: RFC 2822/ISO com timezone; WordPress `date_gmt` é UTC sem offset (tratado explicitamente).
- Itens com texto < 400 caracteres → enriquecimento (trafilatura; Crawl4AI se o extra `browser` estiver instalado), respeitando robots.txt.
- Verificado em: 2026-10-09

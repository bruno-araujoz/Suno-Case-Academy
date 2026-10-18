# Relatório de avaliação em lote — 2026-10-14 06:56 UTC

- Eventos: 3 · gerações: 27 (novas: 26, cache: 1)
- Glossário revisado pelo time: NÃO
- Versão das metas: `levels@f5c2d03ac4`

## Matriz de saídas (mesmo evento, níveis lado a lado)

**artigo** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| Ibovespa recua 1,04% após empate técnico entre Lula e Flávio Bolsonaro; juros sob pressão  O principal índice da bolsa brasileira (Ibovespa) caiu 1,04% e fechou em 206.887,52 pontos depois que pesquisas eleitorais mostraram empate técnico entre Flávio Bolsonaro e Lula. O dólar subiu 0,71% para R$ 5,0204, a mediana do Boletim Focus para o IPCA de 2026 subiu para 5,22% e as taxas… | Ibovespa recua 1,04% após empate técnico nas pesquisas eleitorais e alta do IPCA 2026  O Ibovespa fechou em 206.887,52 pontos, queda de 1,04%, enquanto o dólar avançou 0,71% para R$ 5,0204. Pesquisas do BTG/Nexus (Flávio Bolsonaro 48% x Lula 45%) e PoderData/AYA (Flávio 51% x Lula 49%) apontam empate técnico no segundo turno. O Boletim Focus elevou a mediana do IPCA 2026 de 5,0… | Ibovespa recua e curva de juros reage a pesquisas de segundo turno e Focus  O Ibovespa registrou queda de 1,04% e fechou aos 206.887,52 pontos. O movimento decorre da convergência entre pesquisas eleitorais de segundo turno, novas projeções do Boletim Focus para o IPCA de 2026 e a precificação de ativos em meio à reprecificação do risco soberano e à volatilidade cambial.  Reaçã… |

**carrossel** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| Sua grana sentiu a eleição?. O mercado financeiro brasileiro reagiu hoje. É como um painel de trânsito que muda de cor rápido e afeta o seu bolso e os seus investimentos.  Empate na eleição. A pesquisa BTG/Nexus apontou Flávio Bolsonaro com 48% e Lula com 45% das intenções de voto. Isso é um empate técnico com margem de erro de dois pontos.  Queda na Bolsa. Com isso, o Ibovespa… | Eleicoes e Juros Mexem com o Mercado. Novas pesquisas eleitorais e dados economicos provocam forte volatilidade nos ativos locais nesta sessao.  Queda no Ibovespa. O Ibovespa caiu 1,04% e fechou aos 206.887,52 pontos apos pesquisas eleitorais mostrarem empate tecnico entre Flavio Bolsonaro e Lula.  Cenarios das Pesquisas. A pesquisa BTG/Nexus apontou Flavio Bolsonaro com 48% e … | Ibovespa reage a empate técnico nas pesquisas eleitorais. A divulgação de pesquisas que apontam empate técnico entre Flávio Bolsonaro (48%) e Lula (45%) provocou queda de 1,04% no Ibovespa, que fechou em 206.887,52 pontos, sinalizando volatilidade institucional.  Detalhamento das pesquisas de intenção de voto. A pesquisa BTG/Nexus indica margem de erro de dois pontos percentuai… |

**roteiro** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| A bolsa caiu hoje! Sabe o que isso significa para o seu dinheiro?  O Ibovespa, que é o principal índice que mede o desempenho médio das ações negociadas na bolsa brasileira, é como um termômetro que mede a saúde das ações, caiu 1,04% e fechou aos 206.887,52 pontos.  Isso aconteceu porque pesquisas eleitorais mostraram empate técnico entre Flávio Bolsonaro e Lula no segundo turn… | Ibovespa cai 1,04% e fecha em 206.887,52 pontos.  Pesquisa BTG/Nexus indica empate técnico: Flávio Bolsonaro 48%, Lula 45%, margem de erro de dois pontos.  PoderData/AYA traz Flávio 51% contra 49% para Lula.  DI sobem mais de 20 pontos‑base; Boletim Focus eleva mediana do IPCA 2026 de 5,01% para 5,22%.  Dólar avança 0,71% cotado a R$ 5,0204; ETF EWZ recua em Nova York, sinal de… | O Ibovespa caiu 1,04% e fechou aos 206.887,52 pontos após novas pesquisas eleitorais.  A pesquisa BTG/Nexus apontou Flávio Bolsonaro com 48% e Lula com 45% das intenções de voto, configurando empate técnico com margem de erro de dois pontos percentuais.  Paralelamente, a mediana do Boletim Focus para o IPCA de 2026 subiu de 5,01% para 5,22%. |

## Aprovação por nível × formato

| nível | artigo | carrossel | roteiro |
|---|---|---|---|
| iniciante | 3/3 | 3/3 | 3/3 |
| intermediario | 3/3 | 2/3 | 3/3 |
| avancado | 2/3 | 3/3 | 2/3 |

## Matriz de confusão — regras de especificação

_Mesma régua que guiou a geração: mede o cumprimento da especificação (parcialmente circular)._

Acurácia: **0.852**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 9 | 0 | 0 |
| intermediario | 0 | 7 | 2 |
| avancado | 0 | 2 | 7 |

## Matriz de confusão — classificador independente (centróides externos)

_Centróides: avancado: 171 atas/comunicados do Copom; intermediario: 200 notícias de portais; iniciante: PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)_

Acurácia: **0.481**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 4 | 5 | 0 |
| intermediario | 0 | 7 | 2 |
| avancado | 0 | 7 | 2 |

## Reflection loop

- Gerações que precisaram reescrever: 9 de 27
- Aprovadas após reescrita: 6
- Score médio 1ª tentativa → final (reescritas): 0.806 → 0.94
- Falhas mais comuns na 1ª tentativa: [('analogias', 4), ('densidade técnica (interm.+avanç.)', 4), ('termos intermediario sem explicação', 1), ('termos avancado sem explicação', 1), ('legibilidade (Flesch-PT)', 1)]

## Custo e latência

- Chamadas de LLM no lote: 62 (falhas/failover: 20)
- Tokens: 78180 entrada + 34778 saída
- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, req/dia).

| propósito | chamadas | tokens | latência mediana (ms) |
|---|---|---|---|
| anchor | 2 | 4854 | 3159 |
| write | 60 | 108104 | 1904 |

| formato | latência mediana por geração nova (s) |
|---|---|
| artigo | 5.8 |
| carrossel | 4.4 |
| roteiro | 1.8 |

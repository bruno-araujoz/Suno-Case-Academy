# Relatório de avaliação em lote — 2026-10-18 00:33 UTC

- Eventos: 2 · gerações: 6 (novas: 6, cache: 0)
- Glossário revisado pelo time: NÃO
- Versão das metas: `levels@718f08f0a2`

## Matriz de saídas (mesmo evento, níveis lado a lado)

**artigo** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ibovespa recua 1,04% e DIs sobem mais de 20 pb ante volatilidade eleitoral e IPCA  O Ibovespa recuou 1,04% para 206.887,52 pontos ante pesquisas do segundo turno indicando empate técnico entre Flávio Bolsonaro (48%) e Lula (45%). O dólar avançou 0,71% a R$ 5,0204, enquanto a mediana do Boletim Focus para o IPCA de 2026 subiu de 5,01% para 5,22%. O movimento gerou inclinação na … |

**carrossel** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ajuste na curva de juros e volatilidade no Ibovespa. A divulgação de pesquisas eleitorais para o segundo turno e a revisão das expectativas desancoradas no Boletim Focus geraram estresse na curva de juros e realização de lucros no mercado acionário.  Desempenho dos ativos e pressão cambial. O Ibovespa caiu 1,04% e fechou aos 206.887,52 pontos. O dólar subiu 0,71% e foi cotado a… |

**roteiro** — Ibovespa hoje cai 1% após pesquisas eleitorais mostrarem Lula e Flávio em empate técnico

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | O Ibovespa caiu 1,04% e fechou aos 206.887,52 pontos.  A movimentação refletiu pesquisas eleitorais indicando empate técnico no segundo turno. A pesquisa BTG/Nexus apontou Flávio Bolsonaro com 48% e Lula com 45% das intenções de voto.  O dólar subiu 0,71% cotado a R$ 5,0204. As taxas dos DIs fecharam com altas firmes acima dos 20 pontos-base em vários vencimentos, sob pressão d… |

## Aprovação por nível × formato

| nível | artigo | carrossel | roteiro |
|---|---|---|---|
| iniciante | — | — | — |
| intermediario | — | — | — |
| avancado | 2/2 | 2/2 | 2/2 |

## Matriz de confusão — regras de especificação

_Mesma régua que guiou a geração: mede o cumprimento da especificação (parcialmente circular)._

Acurácia: **1.0**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 0 | 6 |

## Matriz de confusão — classificador independente (centróides externos)

_Centróides: avancado: 171 atas/comunicados do Copom; intermediario: 200 notícias de portais; iniciante: PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)_

Acurácia: **0.833**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 1 | 5 |

## Reflection loop

- Gerações que precisaram reescrever: 1 de 6
- Aprovadas após reescrita: 1
- Score médio 1ª tentativa → final (reescritas): 0.8 → 1.0
- Falhas mais comuns na 1ª tentativa: [('legibilidade (Flesch-PT)', 1)]

## Custo e latência

- Chamadas de LLM no lote: 11 (falhas/failover: 3)
- Tokens: 13935 entrada + 7266 saída
- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, req/dia).

| propósito | chamadas | tokens | latência mediana (ms) |
|---|---|---|---|
| write | 11 | 21201 | 3291 |

| formato | latência mediana por geração nova (s) |
|---|---|
| artigo | 7.6 |
| carrossel | 8.1 |
| roteiro | 2.6 |

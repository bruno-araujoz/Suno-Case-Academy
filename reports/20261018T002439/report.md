# Relatório de avaliação em lote — 2026-10-18 00:24 UTC

- Eventos: 3 · gerações: 27 (novas: 27, cache: 0)
- Glossário revisado pelo time: NÃO
- Versão das metas: `levels@718f08f0a2`

## Matriz de saídas (mesmo evento, níveis lado a lado)

**artigo** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| Ibovespa recua 1,7% e Petrobras sobe 6,6% com Brent perto de US$ 110  Na semana passada a bolsa brasileira (Ibovespa, ou seja, o termômetro das ações do país) fechou em 205.430 pontos, queda de 1,7%. O recuo foi causado por juros mais altos nos EUA, incertezas fiscais e a corrida eleitoral. Enquanto isso, as ações da Petrobras (PETR4) ganharam 6,6% graças ao petróleo Brent próx… | Ibovespa recua com juros nos EUA e fiscal, mas Petrobras avança  O Ibovespa encerrou a semana com queda de 1,7% em reais, fechando aos 205.430 pontos. A bolsa passou por realização de lucros pressionada pelo exterior e por incertezas locais.  Cenário externo e inflação  O núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, ficando acima das expectativas. A alta da infla… | Ibovespa recua com inflação nos EUA e cenário fiscal, enquanto Petrobras avança guiada pelo Brent  O Ibovespa encerrou a semana com queda de 1,7% em reais, aos 205.430 pontos, pressionado pelo avanço do núcleo do CPI nos EUA e pelo aumento dos prêmios de risco decorrentes de incertezas fiscais e do segundo turno eleitoral, embora o Brent a US$ 110 tenha impulsionado a Petrobras… |

**carrossel** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| Sua carteira sentiu a queda da bolsa esta semana?. O Ibovespa (principal índice que mede o desempenho médio das ações negociadas na bolsa brasileira, ou seja, o termômetro das ações do país) recuou 1,7% e fechou em 205.430 pontos. O que isso traz para o seu bolso?  Juros nos EUA apertam o clima. O Fed (Banco Central dos Estados Unidos, responsável por conduzir a política monetá… | Ibovespa recua com pressões externas e fiscais. O mercado acionário brasileiro enfrentou uma semana de realização de lucros, refletindo um cenário desafiador com juros nos EUA e incertezas locais.  Queda semanal do Ibovespa. O Ibovespa encerrou a semana com queda de 1,7% em reais, fechando aos 205.430 pontos, pressionado pelo cenário fiscal e eleições.  Inflação e juros nos Est… | Ibovespa recua com aversao ao risco global e fiscal. O Ibovespa encerrou a semana com queda de 1,7% em reais, fechando aos 205.430 pontos, pressionado pela reprecificacao da curva de juros.  Pressao inflacionaria nos Estados Unidos. O nucleo do CPI nos Estados Unidos avanco 0,33% em setembro, ficando acima das expectativas e elevando premios.  Choque de oferta no mercado de ene… |

**roteiro** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| Sua grana na bolsa parece montanha-russa? Entenda o que aconteceu na semana!  O Ibovespa, que é como o termômetro da saúde das ações brasileiras, caiu 1,7%, fechando em 205.430 pontos.  Lá nos Estados Unidos, a inflação subiu mais que o esperado, 0,33% em setembro. Isso pode fazer o Fed, que é o banco central que controla a política monetária dos EUA, aumentar os juros de novo.… | Ibovespa recuou 1,7%, enquanto Petrobras disparou 6,6%.  O índice fechou a semana em 205.430 pontos, refletindo realização de lucros e temores inflacionários globais.  Nos EUA, o núcleo do CPI avançou 0,33% em setembro, reforçando a expectativa de nova alta de juros pelo Fed.  O petróleo Brent chegou a US$ 110, impulsionando as petroleiras brasileiras e sustentando a alta de PE… | O Ibovespa encerrou a semana com queda de 1,7% em reais, fechando aos 205.430 pontos, refletindo uma forte realização de lucros e expectativas desancoradas na curva de juros.  No cenário externo, o núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, ficando acima das expectativas e elevando a precificação da taxa terminal pelo Fed no forward guidance.  Enquanto isso, a … |

## Aprovação por nível × formato

| nível | artigo | carrossel | roteiro |
|---|---|---|---|
| iniciante | 1/3 | 1/3 | 2/3 |
| intermediario | 2/3 | 2/3 | 2/3 |
| avancado | 2/3 | 1/3 | 2/3 |

## Matriz de confusão — regras de especificação

_Mesma régua que guiou a geração: mede o cumprimento da especificação (parcialmente circular)._

Acurácia: **0.667**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 4 | 5 | 0 |
| intermediario | 0 | 7 | 2 |
| avancado | 0 | 2 | 7 |

## Matriz de confusão — classificador independente (centróides externos)

_Centróides: avancado: 171 atas/comunicados do Copom; intermediario: 200 notícias de portais; iniciante: PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)_

Acurácia: **0.63**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 2 | 7 | 0 |
| intermediario | 0 | 8 | 1 |
| avancado | 0 | 2 | 7 |

## Reflection loop

- Gerações que precisaram reescrever: 22 de 27
- Aprovadas após reescrita: 10
- Score médio 1ª tentativa → final (reescritas): 0.696 → 0.901
- Falhas mais comuns na 1ª tentativa: [('afirmações sem número não apoiadas (juiz)', 16), ('termos intermediario sem explicação', 6), ('termos avancado sem explicação', 5), ('analogias', 4), ('legibilidade (Flesch-PT)', 3)]

## Custo e latência

- Chamadas de LLM no lote: 166 (falhas/failover: 33)
- Tokens: 201605 entrada + 88017 saída
- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, req/dia).

| propósito | chamadas | tokens | latência mediana (ms) |
|---|---|---|---|
| anchor | 4 | 11444 | 2853 |
| judge | 73 | 104270 | 1832 |
| write | 89 | 173908 | 1973 |

| formato | latência mediana por geração nova (s) |
|---|---|
| artigo | 11.0 |
| carrossel | 12.6 |
| roteiro | 24.4 |

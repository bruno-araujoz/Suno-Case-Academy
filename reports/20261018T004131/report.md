# Relatório de avaliação em lote — 2026-10-18 00:41 UTC

- Eventos: 3 · gerações: 9 (novas: 9, cache: 0)
- Glossário revisado pelo time: NÃO
- Versão das metas: `levels@d9b73f1399`

## Matriz de saídas (mesmo evento, níveis lado a lado)

**artigo** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ibovespa recua 1,7% com inflação nos EUA e risco fiscal, mas alta do Brent impulsiona petroleiras  O Ibovespa recuou 1,7% em reais na semana, encerrando aos 205.430 pontos após atingir máximas históricas. O movimento refletiu o avanço de 0,33% no núcleo do CPI nos Estados Unidos e incertezas políticas e fiscais no Brasil. O impacto negativo foi atenuado pela alta de cerca de 6,… |

**carrossel** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ibovespa recua com juros nos EUA e fiscal. O Ibovespa acumulou queda de 1,7% em reais na semana, encerrando aos 205.430 pontos, pressionado pelo cenário externo e doméstico.  Inflação nos Estados Unidos surpreende. O núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, acima do esperado pelo mercado, acelerando apostas sobre o Fed.  Petróleo Brent registra forte alta sem… |

**roteiro** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | O Ibovespa acumulou queda de 1,7% em reais na semana, encerrando aos 205.430 pontos, pressionado pela reprecificação da curva de juros.  O núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, acima do esperado, acelerando apostas sobre a atuação do Fed.  Em contrapartida, a cotação do barril Brent subiu cerca de 6,2% no acumulado semanal, atingindo patamar próximo de US$… |

## Aprovação por nível × formato

| nível | artigo | carrossel | roteiro |
|---|---|---|---|
| iniciante | — | — | — |
| intermediario | — | — | — |
| avancado | 1/3 | 0/3 | 1/3 |

## Matriz de confusão — regras de especificação

_Mesma régua que guiou a geração: mede o cumprimento da especificação (parcialmente circular)._

Acurácia: **0.333**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 6 | 3 |

## Matriz de confusão — classificador independente (centróides externos)

_Centróides: avancado: 171 atas/comunicados do Copom; intermediario: 200 notícias de portais; iniciante: PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)_

Acurácia: **0.444**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 5 | 4 |

## Juiz LLM (afirmações sem número)

- Gerações verificadas: 9 · com alguma afirmação não apoiada: 1 · total de afirmações não apoiadas: 1
  - “Outubro de 2026 registra movimentações acionárias relevantes e prévias operacionais de companhias listadas, impactando a dinâmica da curva de juros e alocações ”

## Reflection loop

- Gerações que precisaram reescrever: 8 de 9
- Aprovadas após reescrita: 1
- Score médio 1ª tentativa → final (reescritas): 0.78 → 0.855
- Falhas mais comuns na 1ª tentativa: [('densidade técnica (interm.+avanç.)', 5), ('afirmações sem número não apoiadas (juiz)', 4), ('legibilidade (Flesch-PT)', 3)]

## Custo e latência

- Chamadas de LLM no lote: 61 (falhas/failover: 13)
- Tokens: 74385 entrada + 30452 saída
- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, req/dia).

| propósito | chamadas | tokens | latência mediana (ms) |
|---|---|---|---|
| judge | 29 | 37042 | 1492 |
| write | 32 | 67795 | 2053 |

| formato | latência mediana por geração nova (s) |
|---|---|
| artigo | 11.6 |
| carrossel | 15.2 |
| roteiro | 9.5 |

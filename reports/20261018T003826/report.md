# Relatório de avaliação em lote — 2026-10-18 00:38 UTC

- Eventos: 3 · gerações: 9 (novas: 9, cache: 0)
- Glossário revisado pelo time: NÃO
- Versão das metas: `levels@cf6f355869`

## Matriz de saídas (mesmo evento, níveis lado a lado)

**artigo** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ibovespa recua 1,7% na semana: juros dos EUA, temores fiscais e alta do Brent sustentam petroleiras  O Ibovespa fechou a semana em 205.430 pontos, queda acumulada de 1,7% em reais, após inflação norte‑americana acima do esperado (CPI núcleo 0,33% em setembro), Brent em alta de 6,2% (US$ 109,7‑110) e pressões fiscais no Brasil. As ações da Prio (+8,8%) e Petrobras (+6,6% e +5,4%… |

**carrossel** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | Ibovespa recua com juros nos EUA e fiscal. O Ibovespa acumulou queda de 1,7% em reais na semana, encerrando aos 205.430 pontos, pressionado pelo cenário externo e prêmios de risco na curva de juros.  Avanço do CPI e pressão sobre o Fed. O núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, acima do esperado pelo mercado, fortalecendo apostas de aperto monetário e revisã… |

**roteiro** — Petrobras (PETR4) sobe mais de 6% e escapa do tombo do Ibovespa; veja o que movimentou a bolsa na semana

| iniciante | intermediário | avançado |
|---|---|---|
| — | — | O Ibovespa acumulou queda de 1,7% em reais na semana, encerrando aos 205.430 pontos, com compressão de múltiplos.  O núcleo do CPI nos Estados Unidos avançou 0,33% em setembro, acima do esperado, alterando o forward guidance da taxa terminal.  A cotação do barril Brent subiu cerca de 6,2% no acumulado semanal, atingindo patamar próximo de US$ 110 e gerando revisões na Taxa Inte… |

## Aprovação por nível × formato

| nível | artigo | carrossel | roteiro |
|---|---|---|---|
| iniciante | — | — | — |
| intermediario | — | — | — |
| avancado | 1/3 | 2/3 | 0/3 |

## Matriz de confusão — regras de especificação

_Mesma régua que guiou a geração: mede o cumprimento da especificação (parcialmente circular)._

Acurácia: **0.556**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 4 | 5 |

## Matriz de confusão — classificador independente (centróides externos)

_Centróides: avancado: 171 atas/comunicados do Copom; intermediario: 200 notícias de portais; iniciante: PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)_

Acurácia: **0.778**

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 0 | 0 | 0 |
| intermediario | 0 | 0 | 0 |
| avancado | 0 | 2 | 7 |

## Juiz LLM (afirmações sem número)

- Gerações verificadas: 9 · com alguma afirmação não apoiada: 3 · total de afirmações não apoiadas: 5
  - “As ações das petroleiras Prio e Petrobras mitigaram a reprecificação de ativos sensíveis ao hiato do produto.”
  - “O ambiente exige reavaliação de VaR e duration, com redução em setores sensíveis ao crédito diante de incertezas fiscais e do forward guidance do Fed.”
  - “As ações das petroleiras Prio e Petrobras se destacaram entre as maiores altas do Ibovespa na semana, blindando o índice com juros futuros elevados.”
  - “Operações que afetam diretamente o P/L, o spread de crédito e o perfil de prazo médio dos ativos envolvidos.”
  - “A integração entre análises de fluxo, operações estruturadas e pré-divulgações de resultados consolida um ambiente de reavaliação de múltiplos como P/L e margem”

## Reflection loop

- Gerações que precisaram reescrever: 6 de 9
- Aprovadas após reescrita: 0
- Score médio 1ª tentativa → final (reescritas): 0.834 → 0.834
- Falhas mais comuns na 1ª tentativa: [('afirmações sem número não apoiadas (juiz)', 3), ('densidade técnica (interm.+avanç.)', 3), ('legibilidade (Flesch-PT)', 1)]

## Custo e latência

- Chamadas de LLM no lote: 49 (falhas/failover: 7)
- Tokens: 55311 entrada + 23813 saída
- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, req/dia).

| propósito | chamadas | tokens | latência mediana (ms) |
|---|---|---|---|
| judge | 23 | 33784 | 1351 |
| write | 26 | 45340 | 1912 |

| formato | latência mediana por geração nova (s) |
|---|---|
| artigo | 11.7 |
| carrossel | 4.5 |
| roteiro | 8.2 |

# Relatório experimental — Suno Content (Entregável 6)

> Período dos experimentos: 2026-10-09 a 2026-10-18. Todos os números vêm de execuções reais
> (fontes e LLMs de verdade), salvas em `reports/` e na tabela `generations`/`llm_calls`.

## 1. Problema e hipótese
O TAPI aponta dois vícios das soluções com LLM: **resumir encurtando** (trivialização) e
**avaliar com outro prompt genérico** (complacência, viés de extensão, nenhuma medida de densidade
conceitual). Nossa hipótese: um pipeline que **verifica os fatos por código** e **avalia por
métricas determinísticas** consegue adaptar o mesmo acontecimento a três públicos de forma
mensurável — e corrigir a si mesmo quando erra.

## 2. Arquitetura (resumo)
```
coleta sob demanda (15 fontes, self-healing) → evento mais relevante (agrupamento + cobertura)
→ âncoras: fatos/números/citações extraídos por LLM e VERIFICADOS por código (cache por evento)
→ brief do nível (glossário em camadas, determinístico) → escrita por formato (LLM, JSON estrito)
→ avaliação determinística (+ juiz estruturado opcional) → reescrita com relatório numérico (≤3)
```
Só **2 chamadas de LLM** no caminho feliz (âncoras e escrita). Detalhes: `README.md`,
`docs/plans/01-scraper.md`, `docs/plans/02-geracao-avaliacao.md`.

## 3. Metodologia do avaliador
| Métrica | Implementação | Justificativa |
|---|---|---|
| Legibilidade | Flesch adaptado ao PT-BR (Martins et al., 1996), sílabas por `pyphen` pt_BR | `textstat` (pt) deu −25,5 onde a fórmula correta dá 15,7 |
| Jargão sem explicação | glossário em camadas + detecção de aposto/"ou seja"/"é como"... na mesma frase ou na seguinte | o iniciante não pode ter termo técnico "solto" (regra do TAPI) |
| Densidade técnica | termos intermediários+avançados por 100 palavras | o avançado não pode ser infantilizado |
| Números sem lastro | todo número da saída precisa existir nas âncoras verificadas | **falha dura** (score 0) |
| Cobertura de fatos | % dos fatos centrais presentes (por número ou por ≥50% das palavras) | bloqueia o "resumo por encurtamento" |
| Regras do formato | slides 6–10 (gancho→conclusão); roteiro ≤60 s e ≤150 palavras, tempos crescentes | estrutura pedida no TAPI |
| Juiz LLM (opcional) | veredito **por afirmação sem número** contra as âncoras, temperatura 0, schema fechado | cobre só o que o código não alcança; não dá "nota de 1 a 10" |

**Âncoras verificadas:** cada fato proposto pelo LLM traz `citacao` literal e `numeros`; o código
mantém o fato só se a citação existir no documento (similaridade ≥ 90 sobre texto sem acentos) e
se os números aparecerem na fonte. Fatos com citação inventada são descartados e listados na UI.

**Glossário:** 244 termos de jargão — semente oficial do BCB (1.171 termos, API), mineração do
corpus (log-odds documento oficial × notícia sobre 382 documentos oficiais e 2.602 notícias, com
filtros de inglês, boilerplate, nomes próprios e palavras comuns via `wordfreq`) e semente manual
com os exemplos do TAPI. Nível/definição/analogia propostos por LLM; **revisão humana pendente**.

## 4. Calibração no corpus
Flesch-PT (p10/p50/p90) e densidade por 100 palavras, medidos em `scripts/calibrate.py corpus`:

| Grupo | Flesch-PT | Densidade técnica (p50) | Avançados/100 (p50) |
|---|---|---|---|
| Atas do Copom (n=86) | 26 / 31 / 37 | ~3,1 | 0,82 |
| Comunicados do Copom (n=82) | 22 / 29 / 36 | ~4,5 | 0,94 |
| Notícias de portais (n=400) | 32 / 45 / 58 | ~0,6 | 0,11 |
| Fatos relevantes/releases (PDF) | 36 / 56 / 69 ⚠️ | — | 0,00 |

Conclusões usadas nas metas (`config/levels.yaml`):
- Flesch separa bem o registro oficial do jornalístico (avançado ≤ 45; intermediário 35–60;
  iniciante ≥ 55 — mais fácil que ~90% das notícias).
- A densidade **só de termos avançados** separa mal (atas p50 0,82 × notícias p90 0,65); a
  **densidade técnica** (intermediários+avançados) separa bem → é a meta do avançado.
- Flesch de PDFs é inflado por tabelas/listas: não serve de régua.
- Não existe corpus confiável de "texto para iniciante": guias educativos da Suno tiveram Flesch
  33–40 (piores que notícia). O iniciante usa a escala de Martins até haver o conjunto rotulado.
- **Ajuste por formato:** fala de vídeo/slides têm frases curtas por natureza (um roteiro
  intermediário ficou com Flesch 66–72 em 3 tentativas) → `format_overrides` por formato.

## 5. Resultados

### 5.1 Lote 1 — 2026-10-14 (27 gerações: 3 eventos × 3 formatos × 3 níveis; sem juiz)
- Aprovação **24/27** (iniciante 9/9).
- Reflexão: 9 reescritas, 6 corrigidas; score médio 0,81 → 0,94.
- Matriz pelas regras da especificação: acurácia **0,85**.
- Matriz independente (centróides externos): acurácia **0,48** — o avançado gerado ficou mais
  perto das notícias (2/9 classificados como avançado).

### 5.2 Ajuste do avançado — comparação controlada (mesmos eventos)
Meta de densidade técnica 1,5 → 2,5 e sugestão de vocabulário técnico do glossário (mesma
categoria do evento) no brief:

| Avançado, mesmos 2 eventos (6 gerações) | Antes | Depois |
|---|---|---|
| Aprovadas | 5/6 | **6/6** |
| Classificador independente = "avançado" | 2/6 | **5/6** |
| Densidade técnica (mín.–máx.) | 1,3–5,0 | **3,1–6,6** |

**A/B das sugestões de vocabulário** (mesmos 3 eventos, com juiz, 9 gerações cada):

| | Com sugestões | Sem sugestões |
|---|---|---|
| Classificador independente = "avançado" | **7/9** | 4/9 |
| Reprovações por densidade técnica | 3 | 5 |
| Afirmações não apoiadas (juiz) | 5 | **1** |
| Aprovadas | 3/9 | 2/9 |

Decisão: manter as sugestões (registro técnico é o que o TAPI pede para o avançado); o custo —
mais afirmações sem lastro — é exatamente o que o juiz detecta e a reescrita corrige.

### 5.3 Lote 2 — 2026-10-18 (27 gerações, novos eventos, juiz LIGADO)
- Aprovação **15/27** (iniciante 4/9, intermediário 6/9, avançado 5/9) — com uma régua mais dura
  (juiz + densidade 2,5) e eventos corporativos (Caixa Seguridade, câmbio, Magalu).
- Matriz pelas regras: acurácia 0,67. **Matriz independente: acurácia 0,63** (0,48 no lote 1):

| pedido \ previsto | iniciante | intermediário | avançado |
|---|---|---|---|
| iniciante | 2 | 7 | 0 |
| intermediário | 0 | 8 | 1 |
| avançado | 0 | 2 | **7** |

- **Juiz × reflexão:** o juiz reprovou **16 primeiras tentativas** por afirmações não numéricas
  sem lastro (a falha mais comum do LLM); nas versões finais restaram **2**. Reescritas: 22/27,
  score médio 0,70 → 0,90.
- O iniciante ficou mais perto do intermediário no classificador independente — esperado
  enquanto o centróide do iniciante é um **prior provisório** (sem conjunto rotulado).

### 5.4 Exemplos (mesmo evento, níveis lado a lado)
Ver "Matriz de saídas" em `reports/20261014T065600/report.md` e `reports/20261018T002439/report.md`.
Exemplo real (artigo avançado sobre a ata da 281ª reunião do Copom): Flesch 35,4, densidade
técnica 6,9/100, 0 analogias, todos os números com lastro (13,75%, 3,2%, 4,9%, 5,2%...) —
aprovado na 1ª tentativa. Carrossel iniciante sobre o Ibovespa: Flesch 70, "O Ibovespa (principal
índice ..., ou seja, é como o termômetro ...)" — aprovado na 3ª tentativa após o avaliador apontar
"termo intermediário sem explicação" e "nenhuma analogia".

## 6. Custo e latência
| Cenário | Chamadas LLM | Tokens (entrada+saída) | Tempo |
|---|---|---|---|
| Pedido no cache | 0 | 0 | ~2 s (+ inicialização) |
| Pedido novo, caminho feliz | 2 (âncoras ~5 mil + escrita ~2 mil) | ~7 mil | 3–8 s |
| Pedido com âncoras do evento em cache | 1 (escrita) | ~2 mil | 2–5 s |
| Pedido com reescritas | até 4 (+ juiz, ~1,5 mil cada) | ~10–15 mil | 10–25 s |
| Lote 1 (27 gerações, sem juiz) | 62 | 113 mil | ~3 min |
| Lote 2 (27 gerações, com juiz) | 166 (33 falhas/failover) | 290 mil | ~8 min |

- Custo monetário **zero** nos planos gratuitos (Groq ×2 chaves, Gemini). O limite real é de
  **cota**: Groq 8k tokens/min por chave; Gemini ~250 req/dia. Mitigações: âncoras em cache por
  evento, roteamento por tamanho (contexto grande → Gemini), espera da renovação da cota,
  provedor em 503 pausado, HTML enxuto para o LLM (99k → 12k caracteres).
- O juiz quase dobra o custo (73 de 166 chamadas no lote 2): por isso é opcional na UI e ligado
  no lote.
- Coleta: rodada incremental 5–20 s; primeira carga de 90 dias ~97 s de pipeline.

## 7. Resiliência observada (self-healing)
- **E-Investidor:** feed parado desde 2026-05-27 → L2 adotou o feed vivo anunciado na home
  (sem LLM). Reproduzível: `scrape.py heal-demo`.
- **L4 com LLM real:** listagem do Money Times com schema de layout antigo → Groq gerou seletores
  novos, validados por contrato antes do uso.
- **Exame:** auditoria independente detectou teasers marcados como texto completo → correção e
  teste de regressão.
- **BCB (2026-10-17):** a API `sitebcb` inteira passou a responder 400; a fonte ficou `failed`
  com motivo e as outras 14 seguiram; o histórico (86 atas) permaneceu no banco.

## 8. Limitações e próximos passos
1. **Glossário não revisado** por humanos (244 termos; 8 definições ainda sem acento).
2. **Conjunto rotulado inexistente** → centróide do iniciante provisório; é o principal motivo
   da baixa acurácia do iniciante na matriz independente.
3. Avançado + juiz: aprovação baixa em eventos corporativos — calibrar a densidade por categoria
   de evento (monetário × corporativo) com mais dados.
4. PDFs escaneados da CVM sem OCR; Flesch não confiável em texto de PDF.
5. Páginas da Agência IBGE bloqueiam acesso automatizado (usamos o resumo oficial da API).
6. Avaliação de concordância humana (métricas × leitores reais) ainda não feita.

## 9. Reprodutibilidade
```bash
bash scripts/bootstrap.sh                        # dependências, banco, histórico, coleta, testes
uv run uvicorn web.app:app --port 8000          # UI (http://localhost:8000)
docker compose --profile app up -d --build       # alternativa: UI em container (http://localhost:8001)
uv run python evaluate.py batch --events 3 --judge
uv run python evaluate.py batch --same-events-as reports/<id>/report.json --levels avancado
uv run pytest                                    # 109 testes offline
```
Toda geração guarda as versões de prompt e o hash de `config/levels.yaml`; toda chamada de LLM
fica em `llm_calls` (provedor, modelo, tokens, latência).

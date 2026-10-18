# Plano 02 — Geração adaptada, avaliador híbrido e MVP de interface

> Status: **implementado — pendências humanas e de calibração abaixo** · atualizado em 2026-10-14

## Contexto
A fase 01 entrega um banco com eventos de mercado já agrupados e pontuados (`documents.cluster_id`,
`relevance_score`, `meta.high_priority`). A fase 02 cobre o núcleo do TAPI (`docs/TAPI.md`).
O usuário escolhe **formato** (artigo analítico | carrossel de Instagram | roteiro de vídeo curto em
texto) e **nível** (iniciante | intermediário | avançado). O sistema escolhe o evento mais relevante,
gera **1 conteúdo**, avalia com métricas **determinísticas** e reescreve até atingir as metas do
nível. Cobre os entregáveis 1–4 e o 6 (o vídeo, entregável 5, é gravado sobre isto).

Duas mudanças na fase 01 entram aqui:
- a coleta passa a ser **sob demanda** (disparada pelo pedido do usuário), atualizando só o que
  mudou, em vez de rodar em cadência fixa;
- o healer ganha um intervalo mínimo entre tentativas (*cooldown*).

## Evidências da pesquisa (2026-10-14, medidas ao vivo)
| Pergunta | Resultado | Consequência |
|---|---|---|
| Saída estruturada | Groq `gpt-oss-120b` e Gemini `2.5-flash` aceitam `json_schema` estrito (endpoints compatíveis com OpenAI); `qwen3.8-27b` no Groq tem limite de 1k tokens de saída/min | camada LLM própria e fina (httpx), com Pydantic na saída; sem LangChain model wrappers |
| Limites | Groq: **8k tokens/min e 1.000 req/dia por chave** (2 chaves). Gemini gratuito: ~10 req/min, 250k tokens/min, **~250 req/dia** (tabela oficial; confirmar no AI Studio) | **roteamento por tamanho**: contexto grande (âncoras) → Gemini; chamadas pequenas e frequentes (escrever/reescrever) → Groq |
| Legibilidade PT | Flesch-PT (Martins 1996, sílabas via `pyphen` pt_BR) no corpus real: atas Copom ~30, fatos relevantes ~32, notícias 41–57. `textstat` (pt) deu −25,5 onde o correto era 15,7 | implementação própria; referências por nível vêm do corpus |
| "Conteúdo para iniciante" existente | guias Suno: Flesch 33–40 (**pior** que notícia); guias InfoMoney ~51 | meta do iniciante ancorada na escala de Martins (50–75 = "fácil") + validação humana; e prova de que o Flesch sozinho não mede nível → avaliador híbrido |
| Glossário oficial | API BCB `/api/servico/sitebcb/glossario`: **1.171 termos** com definição; tem Selic, Copom, IPCA, CDI, curva de juros, swap; **não tem** hiato do produto, forward guidance, taxa neutra, EBITDA, covenant | glossário híbrido: semente oficial + mineração do corpus + curadoria |
| Mineração de jargão | log-odds oficial × notícia: depois de filtrar parágrafos em inglês e boilerplate, surgem termos reais ("direito de retirada", "incorporação de ações", "alienação de controle", "declarações prospectivas") misturados a nomes próprios | candidatos → filtro de entidades → LLM propõe nível/definição/analogia → **revisão humana**; backfill de atas do Copom para o jargão monetário |
| Orquestração | LangGraph 1.2: `StateGraph` tipado, `add_conditional_edges` para o loop, `RetryPolicy` por nó, `stream(stream_mode="updates")` | o grafo transmite o progresso para a UI, nó a nó |

## Iterações do desenho
- **v1 (descartada):** 5 agentes LLM em sequência (anchor → adapter → synthesizer → judge → rewriter)
  dão ~5 chamadas por geração, com o juiz LLM decidindo a qualidade. Isso estoura 8k tokens/min no
  Groq e repete exatamente o viés que o TAPI critica.
- **v2 (descartada):** adapter e synthesizer fundidos e juiz só determinístico. Fica barato, mas sem
  checar afirmações não numéricas, o que deixa uma lacuna na fidelidade.
- **v3 (escolhida):** **2 chamadas de LLM no caminho feliz**:
  - âncoras, feita 1 vez por evento e cacheada;
  - escrita, que já recebe um *brief* de nível montado de forma determinística.

  O avaliador é **determinístico primeiro**. O juiz LLM entra só para afirmações sem número, com
  veredito por afirmação e rubrica fechada. A reescrita acontece no máximo 2 vezes e fica a melhor
  tentativa.

## Arquitetura
```
UI (formato, nível) ─► ensure_fresh (coleta sob demanda, TTL por fonte, trava) ─► select_event
   ─► build_evidence (docs do cluster; enriquece sob demanda só os docs DESTE evento)
   ─► anchor  [LLM Gemini · cache por evento+versão]   fatos/números/citações verificados por código
   ─► level_brief [determinístico]   termos a explicar (glossário), alvos do nível, regras do formato
   ─► write   [LLM Groq · json_schema por formato]
   ─► evaluate [determinístico + juiz LLM opcional p/ afirmações sem número]
   ─► passou? ─não (≤2x)─► write com relatório numérico de falhas (Reflection)
        └sim/limite─► persist (geração + tentativas + métricas + fontes) ─► UI
```

### 1. Coleta sob demanda (`src/scraper/`)
- `sources.yaml` ganha `ttl` por fonte:
  - feeds: 15 min;
  - Google News e IBGE: 1 h;
  - CVM: 6 h;
  - Copom e SGS: 24 h.
- `source_state.checked_at` registra a última checagem por fonte.
- `ensure_fresh(budget_s=20)` roda só as fontes vencidas, dentro de um orçamento de tempo. O que não
  terminar a tempo fica para o próximo pedido, e a UI segue com o banco.
- `pg_advisory_lock` impede duas coletas simultâneas.
- **Cooldown do healer:** após uma falha, nova tentativa só depois de 6 h; o L4 no máximo 1×/dia por
  fonte (`source_state.heal_after`).
- **Enriquecimento sob demanda:** os PDFs da CVM só são baixados quando o evento escolhido precisa
  deles. O backlog geral deixa de ser drenado sem motivo.
- `--watch` continua existindo, mas deixa de ser o modo recomendado. A tabela `source_health` passa
  a ter retenção de 30 dias.

### 2. Camada LLM (`src/llm/`)
- `LLMRouter` sobre httpx (endpoints compatíveis com OpenAI) com:
  - provedores e chaves do `.env` (Groq 1 e 2, Gemini, OpenRouter);
  - limitador por chave (*token bucket*) alimentado pelos headers `x-ratelimit-*`;
  - roteamento por tokens estimados e failover em 429/5xx;
  - `json_schema` estrito com validação Pydantic e 1 reparo em caso de JSON inválido;
  - temperatura baixa e seed quando suportada.
- Toda chamada grava em `llm_calls`: modelo, tokens, latência, custo estimado, `prompt_version`.
  Isso alimenta o relatório de custo e latência.
- Prompts versionados em `prompts/*.md`. O hash do prompt fica gravado em cada geração
  (reprodutibilidade).

### 3. Glossário em camadas (`glossary/terms.yaml` + `src/glossary/`)
**Tudo local em tempo de execução.** As fontes externas (API do BCB e, opcionalmente, o glossário
HTML da CVM no Portal do Investidor) são lidas **uma vez**, só na *construção* do glossário. O
resultado é um arquivo versionado no git (algumas dezenas de KB), carregado na memória quando o
processo inicia. A busca de termos num texto é feita localmente, em milissegundos e sem rede.
Termos desconhecidos vão para uma fila (`glossary/candidates.yaml`), revisada na próxima rodada de
construção. Uma tabela no Postgres pode receber uma cópia para a UI; a fonte de verdade continua
sendo o YAML.

- Campos de cada termo:
  - `termo`, `variantes`, `nivel` (basico | intermediario | avancado), `categoria`;
  - `definicao`, `analogia`, `fonte` (bcb | cvm | corpus | manual).
- Pipeline de construção (`scripts/build_glossary.py`):
  1. Semente: BCB (1.171 termos).
  2. Candidatos do corpus por log-odds (oficial × notícia × frequência no português via `wordfreq`),
     filtrando parágrafos em inglês, boilerplate e nomes próprios (proporção de maiúsculas no corpus).
  3. O LLM propõe nível, definição e analogia em lote.
  4. Revisão humana num arquivo de diff, e só depois entra no YAML.

  Meta: ~300–500 termos úteis, priorizando os que aparecem nos documentos.
- **Backfill das atas do Copom** (2016→hoje), para trazer o jargão monetário.
- Matcher: comparação sem acento e em minúsculas, priorizando a expressão mais longa; siglas
  respeitam maiúsculas. **Sem spaCy no MVP**: a importação é cara no `/mnt/c` e as variantes são
  listadas no glossário. Lematização pode entrar depois, se o recall for baixo.

### 4. Nós do grafo (`src/pipeline/`, LangGraph)
| Nó | Tipo | Saída / regra |
|---|---|---|
| `select_event` | código | Cluster de maior `relevance_score` nas últimas 48 h com texto suficiente. Empate: o que tem doc oficial. |
| `build_evidence` | código | Até 5 docs (oficial primeiro, depois mais veículos e texto mais longo). Comprime até ~12k tokens: frases com números, termos do glossário e lead. |
| `anchor` | LLM (Gemini; Groq com evidência ≤5k tokens) | Saída `Anchors` com: `evento`, `contexto`, `fatos[{id, afirmacao, numeros[], doc_id, citacao}]`, `implicacoes`. O **código verifica** que cada citação existe na fonte (rapidfuzz ≥ 90) e cada número existe (normalizado: "13,75%" ≡ 13.75); o que não confere é descartado. Cache por `cluster_id + hash(docs) + prompt_version`. |
| `level_brief` | código | Termos do glossário presentes nas âncoras, divididos em "pode usar sem explicar" e "precisa explicar (com definição/analogia sugerida)", conforme o nível. Junta alvos numéricos do nível e regras do formato. |
| `write` | LLM (Groq) | Schema por formato. **Artigo:** título, lead, 3–5 seções, conclusão. **Carrossel:** 6–10 slides `{papel: gancho\|corpo\|conclusao, titulo ≤60c, texto ≤280c}`. **Roteiro:** blocos `{inicio_s, fim_s, gancho_visual, fala}`, ≤60 s e ≤150 palavras faladas. |
| `evaluate` | código + juiz opcional | Métricas abaixo; produz `EvalReport` com aprovado/reprovado e falhas acionáveis. |
| `route` | código | Reprovado e tentativas < 3 → `write` com o relatório; senão → `persist` (guarda a melhor tentativa). |

### 5. Avaliador híbrido (`src/evals/`)
| Métrica | Como | Iniciante | Intermediário | Avançado |
|---|---|---|---|---|
| Flesch-PT | Martins (1996) + `pyphen` | ≥ 55 | 38–55 | ≤ 42 |
| Termos avançados sem explicação | glossário + janela (mesma frase ou a seguinte) e marcadores ("ou seja", "que é", "funciona como", "é como se", aposto) | 0 | 0 | — |
| Termos intermediários sem explicação | idem | 0 | livre | livre |
| Densidade de termos avançados /100 palavras | glossário | baixa | média | **mínima** (anti-infantilização) |
| Analogias | marcadores de analogia | ≥ 1 por termo explicado | opcional | ≤ 1 |
| Números sem lastro | todo número da saída tem que existir nas âncoras | **0 (falha dura)** | 0 | 0 |
| Cobertura de âncoras | fatos centrais presentes (por números e entidades) | ≥ 70% | ≥ 80% | ≥ 90% |
| Regras do formato | contagens e limites do schema | todas | todas | todas |
| Fidelidade não numérica | juiz LLM estruturado, por afirmação (apoiada / não apoiada) | sem "não apoiada" | idem | idem |

As faixas acima são **iniciais**. A calibração (passo 4 da implementação) as ajusta com:
- percentis do corpus (oficial ≈ avançado, notícia ≈ intermediário);
- a escala de Martins;
- um **conjunto rotulado pelo time** (~30 textos: 10 por nível), que valida se as métricas
  concordam com humanos.

O Flesch de carrossel e roteiro é medido sobre o texto concatenado, porque textos curtos distorcem
a fórmula.

**Classificador de nível** (para a matriz de confusão): centróide mais próximo no espaço
(Flesch, densidade por camada, termos não explicados, analogias). É calibrado no corpus de
referência e no conjunto rotulado, **não** nas gerações, para evitar circularidade. O relatório
mostra a matriz 3×3, nível pedido × nível previsto.

### 6. Persistência (`sql/006+`)
- `anchors`: cluster_id, docs_hash, prompt_version, json, model, created_at.
- `generations`: id, cluster_id, format, level, content_json, status, attempts, best_attempt,
  passed, latency_ms, tokens, cost.
- `generation_attempts`: generation_id, n, content_json, eval_report_json. Guarda o antes e depois
  da reescrita, que é o entregável 3.
- `llm_calls`.
- **Cache**: o mesmo pedido (evento + formato + nível + versões de prompt) devolve a geração salva,
  sem gerar de novo.

### 7. Interfaces
- CLI `generate.py --format carrossel --level iniciante [--event <cluster_id>] [--no-refresh]`.
- **UI web** (`src/web/`: FastAPI + HTML/CSS/JS puro; substituiu o Streamlit do MVP em 2026-10-18):
  1. Tela "Criar": **tema** (assunto mais relevante agora · assuntos em alta · busca livre com
     ampliação nos portais), formato e nível.
  2. Progresso ao vivo, nó a nó (`stream_mode="updates"` → Server-Sent Events em `POST /api/generate`).
  3. Resultado renderizado por formato (cards de slide, linha do tempo do roteiro, artigo).
  4. Painel de métricas × alvos do nível.
  5. Histórico de tentativas (antes e depois).
  6. Fontes com citação (rastreabilidade).
- Página de relatório com os resultados do lote.
- O MVP foi em Streamlit; como ele reexecuta o script inteiro a cada interação (>10 s por clique
  no WSL), foi trocado por FastAPI + front estático sem build (página pronta em ~0,6 s).

### 8. Suíte de avaliação em lote (entregáveis 2 e 6)
`evaluate.py batch --events N` gera 3 formatos × 3 níveis sobre N eventos. Ela respeita os limites:
as âncoras são reaproveitadas e um agendador por chave controla o ritmo (~35 min para N = 10, só
com cotas gratuitas). Produz:
- a matriz de confusão;
- a taxa de aprovação por nível e formato;
- o ganho médio da reflexão (métricas antes e depois);
- custo, tokens e latência;
- um relatório Markdown + JSON em `reports/`.

`pytest` cobre cada métrica com textos-fixture, além do grafo com o LLM mockado.

## Ordem de implementação (cada passo testável sozinho; nada é commitado)
1. Coleta sob demanda: TTL, `checked_at`, trava, cooldown do healer, enriquecimento sob demanda.
2. `LLMRouter` + prompts versionados + `llm_calls`, com testes por `MockTransport`.
3. Glossário: semente BCB + backfill Copom + mineração + proposta LLM + **revisão humana**.
4. Métricas do avaliador + calibração no corpus + conjunto rotulado (~30 textos, pelo time).
5. Grafo (`select_event` → … → `persist`) + CLI `generate.py`.
6. UI Streamlit do MVP.
7. Lote: classificador, matriz de confusão, relatório.
8. Docs (README, metodologia, custo/latência) e fichas de prompts.

## Riscos e mitigação
- **Cotas gratuitas.**
  - Risco: Groq com 8k tokens/min por chave e Gemini com ~250 req/dia.
  - Mitigação: âncoras cacheadas, 2 chamadas no caminho feliz, roteamento por tamanho, agendador
    no lote e o failover já existente.
- **Glossário depende de curadoria humana.**
  - Risco: o tempo do time para revisar.
  - Mitigação: priorizar os termos que mais aparecem e começar com ~150 termos revisados.
- **Métrica "jogável".**
  - Risco: o LLM encurta frases só para subir o Flesch.
  - Mitigação: a cobertura de âncoras e a densidade mínima no avançado impedem isso. É a resposta
    direta à "trivialização" do TAPI.
- **Circularidade do classificador.**
  - Risco: o classificador aprender com as próprias gerações.
  - Mitigação: calibrar em referência externa e no conjunto rotulado.
- **Coleta sob demanda adiciona latência ao pedido.**
  - Risco: o usuário esperar a coleta.
  - Mitigação: orçamento de 20 s e uso do que já estiver no banco.

## Verificação
- `uv run pytest -m "not live"` verde: métricas, matcher, verificação de âncoras, grafo mockado,
  roteador e coleta sob demanda.
- `uv run python generate.py --format carrossel --level iniciante` contra fontes e LLM reais:
  imprime o conteúdo, as métricas × alvos e as tentativas. Rodar 2 vezes deve usar o cache.
- Demonstração da reflexão: forçar `--level iniciante` num evento de ata do Copom e mostrar a
  1ª tentativa reprovada (termo sem explicação) e a 2ª aprovada.
- UI: `uv run uvicorn web.app:app --port 8000` (http://localhost:8000), escolher um tema, fazer um pedido de ponta a ponta e ver o progresso nó a nó.
- Lote: `evaluate.py batch --events 5` gera `reports/` com a matriz de confusão e o custo.

## Decisões pendentes (do usuário)
1. Aprovar o plano (ou ajustar o escopo do MVP).
2. Quem do time faz a revisão do glossário e a rotulagem dos ~30 textos de calibração.

## Progresso
- [x] 1. Coleta sob demanda (`ondemand.ensure_fresh`, `source_checks`, cooldown do healer, `scrape.py refresh`)
- [x] 2. `LLMRouter` (schema estrito "achatado", reparo, failover, cota por chave, espera de renovação)
- [x] 3. Glossário: semente BCB + backfill Copom (86 atas) + mineração + proposta LLM → 244 termos (**falta revisão humana**)
- [x] 4. Avaliador + calibração no corpus (**falta o conjunto rotulado pelo time**)
- [x] 5. Grafo LangGraph + cache + `generate.py` (verificado ao vivo)
- [x] 6. UI (Streamlit no MVP → FastAPI + front Suno com escolha de tema; E2E no navegador headless)
- [x] 7. Lote + matriz de confusão + relatório (`reports/20261014T065600/`)
- [x] 8. Docs (README, `.claude/rules/evals.md`, regras do scraper)

## Log
- 2026-10-14 (implementação):
  - Groq rejeita o schema cru do Pydantic → `llm/schema.py` achata (sem `$defs`, objetos fechados).
  - Gemini: `2.5-flash-lite` descontinuado (404), `2.5-flash`/`3.5-flash` com 503 frequentes → cadeia
    Groq ×2 → `gemini-3.5-flash` → `3.5-flash-lite` → `2.5-flash`; `reasoning_effort: low` (JSON
    truncado sem isso); provedor em 503 pausado 2 min; espera de renovação de cota (≤ 60 s).
  - Glossário: o LLM às vezes omitia acentos (50/214) → regra no prompt + `--redo-unaccented`;
    sigla ambígua (TIR) → precedência revisado > manual > outros; semente manual com termos do TAPI.
  - Calibração: densidade só de termos avançados separa mal (atas p50 0,82 × notícias p90 0,65) →
    meta do avançado virou **densidade técnica** (interm.+avanç.) ≥ 1,5/100; Flesch de PDF é inflado.
  - Ao vivo: carrossel iniciante aprovado na 3ª tentativa (falhas: termo sem explicação, sem
    analogia); artigo avançado sobre a ata 281 aprovado na 1ª (Flesch 35, densidade técnica 6,9).
  - Posts "ao vivo" (InfoMoney) misturavam assuntos num documento → excluídos da seleção de eventos.
  - UI: roteiro intermediário reprovou 3× só no Flesch (66–72 > teto 60): fala de vídeo tem frases
    curtas por natureza → `format_overrides` em `levels.yaml` (provisório até a matriz do lote);
    hash do `levels.yaml` entra na chave de cache (mudar meta invalida o cache).
  - Matriz de confusão com 2 classificadores: regras da especificação (parcialmente circular) e
    centróides externos (atas/comunicados = avançado, notícias = intermediário, iniciante =
    conjunto rotulado — prior provisório de Martins enquanto o time não rotula).
- 2026-10-14 — **lote real** (3 eventos × 3 formatos × 3 níveis = 27 gerações, ~3 min, 62 chamadas
  de LLM, 113k tokens, custo monetário 0 nos planos gratuitos):
  - aprovação 24/27 (iniciante 9/9); reflexão: 9 reescritas, 6 corrigidas, score 0,81 → 0,94;
  - matriz pelas regras da especificação: acurácia 0,85;
  - **matriz independente (centróides externos): acurácia 0,48** — o "avançado" gerado fica mais
    perto das notícias (densidade técnica ~1,5–2) do que das atas (~4,0); o iniciante usa centróide
    provisório. **Próximos ajustes:** (1) subir `technical_density_min` do avançado na direção do
    registro oficial e medir de novo; (2) conjunto rotulado pelo time para o centróide do
    iniciante; (3) revisão humana do glossário.
- 2026-10-17/18 — **fechamento** (sem commits, a pedido do usuário):
  - Reprodutibilidade: `scripts/bootstrap.sh` testado num banco vazio (1m48s, 3.203 docs, testes
    verdes); `Dockerfile` + serviço `app` (profile) testado (hoje em http://localhost:8001, uvicorn).
  - Incidente real: API `sitebcb` do BCB inteira respondendo 400 (até o glossário); fonte
    marcada `failed`, demais seguiram; documentado em `docs/sources/bcb_copom.md`.
  - `--demo-reflection` (1ª escrita sem adaptação ao público): 1ª tentativa reprova sempre,
    score sobe a cada reescrita, final aprovada em 2/3 execuções.
  - Avançado: densidade técnica 1,5 → 2,5 + sugestão de vocabulário do glossário; comparação
    controlada (mesmos eventos): centróide=avançado 2/6 → 5/6, aprovação 5/6 → 6/6. A/B das
    sugestões com juiz: 7/9 × 4/9 no centróide, custo 5 × 1 afirmações não apoiadas → mantidas.
  - Lote 2 com juiz (novos eventos): 15/27; matriz independente 0,48 → 0,63; o juiz reprovou 16
    primeiras tentativas por afirmações sem lastro, restaram 2 nas versões finais.
  - Entregáveis escritos: `docs/RELATORIO.md`, `docs/VIDEO.md`.
- 2026-10-18 — **escolha de tema + nova interface**:
  - Busca local full-text (`sql/009_search.sql`: `unaccent` + `tsvector` gerado + GIN;
    `Database.search_events` agrupa por cluster) em 5–18 ms; sem resultado → busca WP-JSON
    `?search=` em Suno, InfoMoney, Money Times e Seu Dinheiro (`searchable: true`, orçamento 8 s)
    → ingestão → `RelevanceStage` (ex.: "Ambev cerveja": 5 docs de 3 portais em 2,2 s).
  - `generations.topic` registra o tema; "assunto mais relevante agora" é a opção padrão explícita.
  - API FastAPI (`src/web/app.py`, recursos compartilhados no `lifespan`, SSE nativo) + front
    minimalista nas cores da Suno (`src/web/static/`). E2E: busca "Petrobras" 0,45 s com o fato
    relevante oficial no topo; geração 9,5 s aprovada; avançado via cache 2,1 s; sem overflow no
    celular. Streamlit removido (`app/`, dependência).
- 2026-10-14: v1 → v3 (ver "Iterações do desenho"), com base na pesquisa ao vivo acima.

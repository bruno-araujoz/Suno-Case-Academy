# TAPI — Case Suno Content (Academy × Finance)

Resumo do case original (PDF "Case Suno __ Academy __ Finance") + decisões do time que **não
estão no documento**. Esta é a referência de escopo para qualquer sessão.

## Em uma frase
Pipeline em grafo com estado que recebe documentos financeiros densos e gera conteúdo para
**3 níveis** (Iniciante, Intermediário, Avançado) × **formatos de mídia**, com um
**Avaliador Híbrido** determinístico que prova que cada nível foi respeitado — sem
trivializar por encurtamento. *O gerador é o meio; o avaliador é o produto (Eval-Driven Development).*

## Problemas que o case ataca
1. **Trivialização:** resumir = cortar frases / infantilizar, perdendo nuance macro.
2. **LLM-as-judge subjetivo:** viés de complacência e de extensão, sem medir densidade conceitual.

## Pergunta norteadora
Como desenhar e avaliar um pipeline de IA que adapta documentos regulatórios/financeiros para
públicos e formatos diferentes, garantindo rigor conceitual, adequação de vocabulário e
fidelidade factual por meio de métricas objetivas e determinísticas?

## Matriz de adaptação
| Nível | Regra |
|---|---|
| Iniciante | Zero jargão sem analogia cotidiana; foco no impacto no bolso |
| Intermediário | Vocabulário padrão (CDI, Selic, IPCA, dividendos); alocação e tendências |
| Avançado | Jargão pleno preservado (curva de juros, forward guidance, hiato do produto, EBITDA ajustado, covenants) |

Formatos: Artigo analítico · Carrossel (gancho/corpo/conclusão) · ~~Roteiro de vídeo~~ (ver decisões).

## Avaliador híbrido (núcleo)
- Legibilidade Flesch adaptada ao PT-BR (Martins et al., 1996).
- Domain Term Density Score contra glossário financeiro **em camadas** (densidade + contextualização).
- Factuality & Grounding Checker contra o documento fonte (números devem existir na fonte).
- Refinement/Reflection Loop: reprocessa com feedback numérico se o nível não for atendido.
- Matriz de confusão de níveis (nível pretendido × nível previsto pelas métricas).

## Arquitetura sugerida
Extractor & Anchor → Audience Adapters (paralelos) → Format Synthesizers → Hybrid Evaluator →
Conditional Retry (Reflection). Sugestões: LangGraph/Pydantic AI, textstat, spaCy, DeepEval/Ragas,
pytest, Streamlit/Gradio/FastAPI+React.

## Entregáveis
1. Pipeline em grafo + GitHub com contribuições consistentes
2. Suíte de avaliação híbrida reprodutível + testes
3. Reflection loop demonstrado (antes/depois numérico)
4. Interface/dashboard com rastreabilidade de fontes e scores
5. Vídeo demonstrativo (**máx. 5 min** — critério eliminatório: precisa provar o código real funcionando)
6. README/relatório: metodologia, matriz de confusão, custo/latência, reprodutibilidade

**Fora do escopo:** publicação em redes, renderização de vídeo/avatar, cotações em tempo real.

## Decisões do time (não estão no TAPI)
- **Entrada via scraping próprio:** o sistema é alimentado por um scraper self-healing de
  notícias e documentos do mercado financeiro (oficiais + notícias). Plano: [plans/01-scraper.md](plans/01-scraper.md).
- **Sem saída em vídeo:** o formato "roteiro de vídeo" não será produzido como vídeo. Definição
  do formato substituto fica para a fase de geração.
- **Stack:** Python 3.11+, uv, PostgreSQL (Docker), LLM com cadeia de fallback
  (OpenRouter → Groq → Gemini → Ollama).

## Pontos de atenção do documento
- Duração do vídeo conflita (5–7 min na seção 6 vs. máx. 5 min na seção 7) → seguir 5 min.
- "Flesch-Kincaid" e "Flesch Reading Ease" usados como sinônimos → escolher e justificar.
- Nenhum limiar numérico definido → calibrar empiricamente e documentar.

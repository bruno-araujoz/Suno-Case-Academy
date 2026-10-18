---
paths:
  - "src/evals/**"
  - "config/levels.yaml"
  - "scripts/calibrate.py"
---

# Regras do avaliador

- Métricas são **determinísticas**: mesmo texto → mesmo resultado. Nada de LLM em
  `readability.py`, `jargon.py`, `grounding.py`, `evaluator.py`. O único LLM permitido é o juiz
  opcional (`judge.py`), estruturado, por afirmação e só para afirmações SEM número.
- Número sem lastro nas âncoras é falha **dura** (score 0). Não afrouxe isso.
- Metas vivem em `config/levels.yaml` (nível + `format_overrides`). Toda mudança de meta precisa de
  evidência (corpus via `scripts/calibrate.py`, conjunto rotulado ou matriz de confusão do lote) e
  um comentário no YAML com a data e o motivo. O hash do arquivo entra na chave de cache.
- Marcadores de explicação/analogia casam no texto em minúsculas **com acento** ("é como" ≠ "e como").
- Testes de métricas usam glossário e textos fixos (não dependem de `glossary/candidates.yaml`).
- O classificador independente da matriz de confusão é calibrado em referências externas
  (corpus/rotulado), nunca nas próprias gerações.

---
paths:
  - "tests/**"
---

# Regras de testes

- Testes padrão são **offline**: usam respostas gravadas em `tests/fixtures/<fonte>/`
  (capture com `/capture-fixture`). Para rede real, marque `@pytest.mark.live`.
- Nunca edite fixture para fazer teste passar. Se a fonte mudou, recapture e registre no
  `.meta.json`; se o código está errado, corrija o código.
- Para self-healing, mantenha pares de fixtures: `<fonte>/v1.html` (layout original) e
  `<fonte>/v2_broken.html` (classes/estrutura alteradas). O teste prova: schema v1 falha no
  contrato → healer gera v2 → v2 passa. Mocke a chamada de LLM do healer com um schema fixo.
- Um teste por cenário de quebra (campo ausente, lista vazia, data inválida, URL de outro
  domínio, HTML que é só menu/cookie banner).
- Testes async usam `asyncio_mode = auto` (sem decorator). Nada de `sleep` real: injete jitter 0.

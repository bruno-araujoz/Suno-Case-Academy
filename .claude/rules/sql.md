---
paths:
  - "sql/**"
  - "src/**/db.py"
---

# Regras de SQL / persistência

- Migrations numeradas (`001_*.sql`, `002_*.sql`…) e **idempotentes** (`IF NOT EXISTS`); nunca
  edite uma migration já aplicada — crie a próxima.
- Unicidade NULL-safe: índice funcional com `COALESCE` e o `ON CONFLICT` repetindo exatamente a
  mesma expressão.
- Timestamps `TIMESTAMPTZ`. Status como texto com valores documentados no comentário da coluna.
- Se um dia houver fila de trabalho no banco: `SELECT ... FOR UPDATE SKIP LOCKED` em transação
  (hoje a fila é em memória, no pipeline em streaming).
- asyncpg com queries parametrizadas (`$1`), nunca f-string em SQL.

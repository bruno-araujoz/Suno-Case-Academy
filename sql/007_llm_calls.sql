-- Cada chamada de LLM (custo, latência, reprodutibilidade). Alimenta o relatório de custo/latência.
CREATE TABLE IF NOT EXISTS llm_calls (
    id             BIGSERIAL PRIMARY KEY,
    at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    provider       TEXT NOT NULL,           -- groq | gemini | openrouter | ollama
    model          TEXT NOT NULL,
    key_label      TEXT,                    -- nome da variável da chave (nunca o valor)
    purpose        TEXT NOT NULL,           -- anchor | write | judge | glossary | ...
    prompt_version TEXT,
    in_tokens      INTEGER,
    out_tokens     INTEGER,
    latency_ms     INTEGER,
    ok             BOOLEAN NOT NULL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_at ON llm_calls (at DESC);

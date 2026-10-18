-- Fase 02: âncoras (gabarito verificado por evento), gerações e tentativas (reflection).
CREATE TABLE IF NOT EXISTS anchors (
    id             BIGSERIAL PRIMARY KEY,
    cluster_id     TEXT NOT NULL,
    docs_hash      TEXT NOT NULL,            -- hash dos documentos usados (muda se a evidência mudar)
    prompt_version TEXT NOT NULL,
    anchors        JSONB NOT NULL,           -- Anchors validado (só fatos que passaram na verificação)
    evidence       JSONB NOT NULL,           -- documentos/trechos enviados ao LLM (rastreabilidade)
    dropped        JSONB NOT NULL DEFAULT '[]'::jsonb,  -- fatos descartados na verificação e o motivo
    provider       TEXT,
    model          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, docs_hash, prompt_version)
);

CREATE TABLE IF NOT EXISTS generations (
    id              BIGSERIAL PRIMARY KEY,
    cluster_id      TEXT NOT NULL,
    event_title     TEXT,
    fmt             TEXT NOT NULL,           -- artigo | carrossel | roteiro
    level           TEXT NOT NULL,           -- iniciante | intermediario | avancado
    prompt_versions TEXT NOT NULL,           -- versões de prompt (cache + reprodutibilidade)
    anchors_id      BIGINT REFERENCES anchors(id),
    content         JSONB NOT NULL,          -- melhor tentativa
    eval            JSONB NOT NULL,          -- EvalReport da melhor tentativa
    passed          BOOLEAN NOT NULL,
    score           REAL NOT NULL,
    attempts        INTEGER NOT NULL,
    best_attempt    INTEGER NOT NULL,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cluster_id, fmt, level, prompt_versions)
);

CREATE TABLE IF NOT EXISTS generation_attempts (
    generation_id BIGINT NOT NULL REFERENCES generations(id) ON DELETE CASCADE,
    n             INTEGER NOT NULL,
    content       JSONB NOT NULL,
    eval          JSONB NOT NULL,
    provider      TEXT,
    model         TEXT,
    latency_ms    INTEGER,
    PRIMARY KEY (generation_id, n)
);

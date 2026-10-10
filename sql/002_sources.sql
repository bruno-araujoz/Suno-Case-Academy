-- Estado incremental e saúde por fonte (base do self-healing). Idempotente.
CREATE TABLE IF NOT EXISTS source_state (
    source         TEXT NOT NULL,
    endpoint_key   TEXT NOT NULL,          -- identifica o endpoint dentro da fonte (ex.: 'atas', 'feed')
    endpoint       TEXT NOT NULL,          -- URL atual (pode mudar via healer L2)
    etag           TEXT,
    last_modified  TEXT,
    watermark      TIMESTAMPTZ,            -- maior published_at já visto
    schema_version INTEGER NOT NULL DEFAULT 1,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, endpoint_key)
);

CREATE TABLE IF NOT EXISTS source_health (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,             -- ok | not_modified | degraded | healed | failed
    level       TEXT,                      -- L0..L4: degrau usado quando houve reparo
    items_seen  INTEGER NOT NULL DEFAULT 0,
    items_valid INTEGER NOT NULL DEFAULT 0,
    items_new   INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    error       TEXT,
    duration_ms INTEGER,
    run_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_source_health_source ON source_health (source, run_at DESC);

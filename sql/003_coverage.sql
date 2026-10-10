-- Sinais de cobertura (Google News, Valor): manchetes sem texto usadas na relevância.
CREATE TABLE IF NOT EXISTS coverage_signals (
    id         BIGSERIAL PRIMARY KEY,
    url_hash   TEXT NOT NULL UNIQUE,
    publisher  TEXT NOT NULL,
    title      TEXT NOT NULL,
    url        TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    cluster_id TEXT,
    seen_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_coverage_cluster ON coverage_signals (cluster_id);

-- Documentos coletados (oficiais e notícias). Idempotente.
CREATE TABLE IF NOT EXISTS documents (
    id               BIGSERIAL PRIMARY KEY,
    url_hash         TEXT NOT NULL UNIQUE,          -- xxh3_64 da URL canônica (dedupe exato)
    url              TEXT NOT NULL,
    source           TEXT NOT NULL,
    tier             TEXT NOT NULL,                 -- official | news | coverage
    doc_type         TEXT NOT NULL,                 -- copom_ata | copom_comunicado | fato_relevante | press_release | ibge_release | news
    title            TEXT NOT NULL,
    published_at     TIMESTAMPTZ NOT NULL,
    author           TEXT,
    content_text     TEXT,
    content_hash     TEXT,                          -- xxh3_64 do texto normalizado (dedupe de conteúdo)
    pdf_url          TEXT,
    extraction_level TEXT NOT NULL DEFAULT 'none',  -- api | feed | pdf | article | browser | none
    status           TEXT NOT NULL DEFAULT 'ready', -- ready | pending_enrich | failed
    relevance_score  REAL,
    cluster_id       TEXT,
    meta             JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_documents_published ON documents (published_at DESC);
CREATE INDEX IF NOT EXISTS ix_documents_source ON documents (source, published_at DESC);
CREATE INDEX IF NOT EXISTS ix_documents_content_hash ON documents (content_hash);
CREATE INDEX IF NOT EXISTS ix_documents_pending ON documents (status) WHERE status <> 'ready';
CREATE INDEX IF NOT EXISTS ix_documents_cluster ON documents (cluster_id);

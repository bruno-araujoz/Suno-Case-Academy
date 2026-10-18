-- Escolha de tema: busca full-text em português, sem acentos, sobre título + texto.
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() não é IMMUTABLE; colunas geradas/índices exigem. Wrapper com dicionário fixo.
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS search tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('portuguese', f_unaccent(title)), 'A') ||
    setweight(to_tsvector('portuguese', f_unaccent(left(coalesce(content_text, ''), 20000))), 'B')
) STORED;
CREATE INDEX IF NOT EXISTS ix_documents_search ON documents USING GIN (search);

-- Tema escolhido pelo usuário (texto livre ou null = "assunto mais relevante").
ALTER TABLE generations ADD COLUMN IF NOT EXISTS topic TEXT;

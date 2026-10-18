"""Async persistence (asyncpg): migrations, bulk upserts and incremental source state."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg

from .config import Settings, get_settings
from .logging import get_logger
from .models import Document

log = get_logger("db")

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"

_UPSERT_DOCUMENT = """
INSERT INTO documents (
    url_hash, url, source, tier, doc_type, title, published_at, author, content_text,
    content_hash, pdf_url, extraction_level, status, relevance_score, cluster_id, meta
) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb)
ON CONFLICT (url_hash) DO UPDATE SET
    title            = EXCLUDED.title,
    content_text     = COALESCE(EXCLUDED.content_text, documents.content_text),
    content_hash     = COALESCE(EXCLUDED.content_hash, documents.content_hash),
    pdf_url          = COALESCE(EXCLUDED.pdf_url, documents.pdf_url),
    extraction_level = EXCLUDED.extraction_level,
    status           = EXCLUDED.status,
    relevance_score  = COALESCE(EXCLUDED.relevance_score, documents.relevance_score),
    cluster_id       = COALESCE(EXCLUDED.cluster_id, documents.cluster_id),
    meta             = documents.meta || EXCLUDED.meta,
    updated_at       = now()
-- Skip no-op rewrites: only touch the row when something actually changed.
WHERE documents.content_hash IS DISTINCT FROM EXCLUDED.content_hash
   OR documents.status IS DISTINCT FROM EXCLUDED.status
   OR documents.relevance_score IS DISTINCT FROM EXCLUDED.relevance_score
   OR documents.cluster_id IS DISTINCT FROM EXCLUDED.cluster_id
"""


@dataclass(slots=True)
class SourceState:
    source: str
    endpoint_key: str
    endpoint: str
    etag: str | None = None
    last_modified: str | None = None
    watermark: datetime | None = None
    schema_version: int = 1
    kind: str | None = None  # overrides the configured kind after a repair (rss|wpjson|html)


def _document_row(doc: Document) -> tuple:
    return (
        doc.url_hash,
        doc.url,
        doc.source,
        doc.tier,
        doc.doc_type,
        doc.title,
        doc.published_at,
        doc.author,
        doc.content_text,
        doc.content_hash,
        doc.pdf_url,
        doc.extraction_level,
        doc.status,
        doc.relevance_score,
        doc.cluster_id,
        json.dumps(doc.meta, default=str),
    )


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() precisa ser chamado antes.")
        return self._pool

    async def connect(self) -> Database:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.settings.database_url, min_size=1, max_size=8
            )
        return self

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def __aenter__(self) -> Database:
        return await self.connect()

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def migrate(self) -> list[str]:
        """Apply sql/*.sql once each, in order, tracked in schema_migrations."""
        applied: list[str] = []
        async with self.pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
            for path in sorted(SQL_DIR.glob("*.sql")):
                if path.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(path.read_text(encoding="utf-8"))
                    await conn.execute(
                        "INSERT INTO schema_migrations (name) VALUES ($1)", path.name
                    )
                applied.append(path.name)
        if applied:
            log.info("Migrations aplicadas: %s", ", ".join(applied))
        return applied

    # ------------------------------------------------------------------ documents

    async def upsert_documents(self, docs: Iterable[Document]) -> int:
        rows = [_document_row(d) for d in docs]
        if not rows:
            return 0
        async with self.pool.acquire() as conn:
            await conn.executemany(_UPSERT_DOCUMENT, rows)
        return len(rows)

    async def known_url_hashes(self, since: datetime | None = None) -> set[str]:
        """Every stored hash, any status — preloaded so the dedupe gate is in-memory.

        Pending documents are included on purpose: they are retried by the backlog loader
        (`pending_documents`), not re-emitted by their source as if they were new.
        """
        query = "SELECT url_hash FROM documents"
        args: list[object] = []
        if since is not None:
            query += " WHERE published_at >= $1"
            args.append(since)
        async with self.pool.acquire() as conn:
            return {r["url_hash"] for r in await conn.fetch(query, *args)}

    async def pending_documents(self, limit: int = 500) -> list[Document]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source, doc_type, tier, url, title, published_at, author, content_text, "
                "pdf_url, extraction_level, status, meta FROM documents "
                "WHERE status = 'pending_enrich' ORDER BY published_at DESC LIMIT $1",
                limit,
            )
        return [Document(**{**dict(r), "meta": json.loads(r["meta"])}) for r in rows]

    # ------------------------------------------------------------------ relevance

    async def recent_for_clustering(self, since: datetime) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT url_hash, title, source, tier, published_at, cluster_id, "
                "left(content_text, 300) AS lead, (meta->'relevance'->>'lexical')::real AS lexical "
                "FROM documents WHERE published_at >= $1",
                since,
            )

    async def recent_coverage(self, since: datetime) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT url_hash, publisher, title, url, published_at FROM coverage_signals "
                "WHERE coalesce(published_at, seen_at) >= $1",
                since,
            )

    async def upsert_coverage(self, rows: list[tuple]) -> int:
        """rows: (url_hash, publisher, title, url, published_at, cluster_id)"""
        if not rows:
            return 0
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO coverage_signals (url_hash, publisher, title, url, published_at, "
                "cluster_id) VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (url_hash) DO UPDATE SET "
                "cluster_id = EXCLUDED.cluster_id",
                rows,
            )
        return len(rows)

    async def update_relevance(self, rows: list[tuple[str, str, float, str]]) -> int:
        """rows: (url_hash, cluster_id, relevance_score, meta_patch_json)"""
        if not rows:
            return 0
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "UPDATE documents SET cluster_id=$2, relevance_score=$3, "
                "meta = meta || $4::jsonb, updated_at=now() WHERE url_hash=$1",
                rows,
            )
        return len(rows)

    # ------------------------------------------------------------------ source state / health

    async def get_state(self, source: str, endpoint_key: str) -> SourceState | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT source, endpoint_key, endpoint, etag, last_modified, watermark, "
                "schema_version, kind FROM source_state WHERE source=$1 AND endpoint_key=$2",
                source,
                endpoint_key,
            )
        return SourceState(**dict(row)) if row else None

    async def save_state(self, state: SourceState) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO source_state
                    (source, endpoint_key, endpoint, etag, last_modified, watermark,
                     schema_version, kind)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (source, endpoint_key) DO UPDATE SET
                    endpoint = EXCLUDED.endpoint, etag = EXCLUDED.etag,
                    last_modified = EXCLUDED.last_modified,
                    watermark = GREATEST(source_state.watermark, EXCLUDED.watermark),
                    schema_version = EXCLUDED.schema_version, kind = EXCLUDED.kind,
                    updated_at = now()
                """,
                state.source,
                state.endpoint_key,
                state.endpoint,
                state.etag,
                state.last_modified,
                state.watermark,
                state.schema_version,
                state.kind,
            )

    async def record_health(self, run_id: str, report: dict) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO source_health (run_id, source, status, level, items_seen, items_valid,"
                " items_new, http_status, error, duration_ms) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                run_id,
                report["source"],
                report["status"],
                report.get("level"),
                report.get("items_seen", 0),
                report.get("items_valid", 0),
                report.get("items_new", 0),
                report.get("http_status"),
                report.get("error"),
                report.get("duration_ms"),
            )

    async def health_baseline(self, source: str, runs: int = 10) -> float | None:
        """Median of entries read in the last healthy runs (for drift detection)."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY items_seen) FROM ("
                "  SELECT items_seen FROM source_health WHERE source=$1 AND status IN "
                "  ('ok','healed') ORDER BY run_at DESC LIMIT $2) t",
                source,
                runs,
            )

    async def latest_health(self) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT DISTINCT ON (source) source, status, level, items_seen, items_valid, "
                "items_new, http_status, error, duration_ms, run_at FROM source_health "
                "ORDER BY source, run_at DESC"
            )

    # ------------------------------------------------------------------ on-demand checks

    async def get_checks(self) -> dict[str, datetime | None]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT source, checked_at FROM source_checks")
        return {r["source"]: r["checked_at"] for r in rows}

    async def mark_checked(self, sources: list[str], at: datetime) -> None:
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO source_checks (source, checked_at) VALUES ($1, $2) "
                "ON CONFLICT (source) DO UPDATE SET checked_at = EXCLUDED.checked_at",
                [(s, at) for s in sources],
            )

    async def get_heal_after(self, source: str) -> datetime | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT heal_after FROM source_checks WHERE source = $1", source
            )

    async def set_heal_after(self, source: str, until: datetime | None) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO source_checks (source, heal_after) VALUES ($1, $2) "
                "ON CONFLICT (source) DO UPDATE SET heal_after = EXCLUDED.heal_after",
                source,
                until,
            )

    async def prune_health(self, days: int = 30) -> int:
        async with self.pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM source_health WHERE run_at < now() - make_interval(days => $1)", days
            )
        return int(status.split()[-1])

    async def documents_by_hashes(self, hashes: list[str]) -> list[Document]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source, doc_type, tier, url, title, published_at, author, content_text, "
                "pdf_url, extraction_level, status, meta FROM documents WHERE url_hash = ANY($1)",
                hashes,
            )
        return [Document(**{**dict(r), "meta": json.loads(r["meta"])}) for r in rows]

    # ------------------------------------------------------------------ llm calls

    async def record_llm_call(self, info: Any) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO llm_calls (provider, model, key_label, purpose, prompt_version, "
                "in_tokens, out_tokens, latency_ms, ok, error) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                info.provider,
                info.model,
                info.key_label,
                info.purpose,
                info.prompt_version,
                info.in_tokens,
                info.out_tokens,
                info.latency_ms,
                info.ok,
                info.error,
            )

    # ------------------------------------------------------------------ generation (phase 02)

    async def top_events(self, window_hours: int = 48, limit: int = 5) -> list[asyncpg.Record]:
        """Most relevant event clusters with enough material to write about."""
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                WITH c AS (
                    SELECT cluster_id,
                           max(relevance_score) AS score,
                           max(published_at) AS last_at,
                           bool_or(tier = 'official') AS has_official,
                           sum(length(coalesce(content_text, ''))) AS chars,
                           max(coalesce((meta->'relevance'->>'publishers')::int, 1)) AS publishers,
                           count(*) AS docs,
                           (array_agg(title ORDER BY relevance_score DESC NULLS LAST))[1] AS title
                    FROM documents
                    WHERE cluster_id IS NOT NULL
                      AND published_at > now() - make_interval(hours => $1)
                      AND status IN ('ready', 'pending_enrich')
                      -- live blogs mix many unrelated stories in one document
                      AND url NOT ILIKE '%ao-vivo%' AND title NOT ILIKE '%ao vivo%'
                    GROUP BY cluster_id
                )
                SELECT * FROM c WHERE chars >= 1200 OR has_official
                ORDER BY score DESC NULLS LAST, has_official DESC, publishers DESC
                LIMIT $2
                """,
                window_hours,
                limit,
            )

    async def search_events(
        self, query: str, window_days: int = 21, limit: int = 8, min_rank: float = 0.05
    ) -> list[asyncpg.Record]:
        """Events (clusters) matching a free-text topic — Portuguese full text, accent-insensitive.

        Ranking: best text match × (0.5 + event relevance), with a small bonus for clusters that
        contain an official document. Same card fields as `top_events`, plus `rank` and `snippet`.
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                """
                WITH q AS (SELECT websearch_to_tsquery('portuguese', f_unaccent($1)) AS query),
                hits AS (
                    SELECT d.cluster_id, d.title, d.published_at, d.relevance_score, d.tier,
                           d.content_text, d.meta, ts_rank(d.search, q.query) AS rank
                    FROM documents d, q
                    WHERE d.search @@ q.query
                      AND d.cluster_id IS NOT NULL
                      AND d.published_at > now() - make_interval(days => $2)
                      AND d.status IN ('ready', 'pending_enrich')
                      AND d.url NOT ILIKE '%ao-vivo%' AND d.title NOT ILIKE '%ao vivo%'
                    ORDER BY rank DESC
                    LIMIT 300
                ),
                clusters AS (
                    SELECT cluster_id,
                           max(rank) AS rank,
                           max(relevance_score) AS score,
                           count(*) AS docs,
                           bool_or(tier = 'official') AS has_official,
                           max(published_at) AS last_at,
                           max(coalesce((meta->'relevance'->>'publishers')::int, 1)) AS publishers,
                           (array_agg(title ORDER BY rank DESC))[1] AS title,
                           (array_agg(left(coalesce(content_text, ''), 2500)
                                      ORDER BY rank DESC))[1] AS best_text
                    FROM hits GROUP BY cluster_id
                )
                SELECT c.cluster_id, c.title, c.score, c.docs, c.has_official, c.last_at,
                       c.publishers, c.rank,
                       ts_headline('portuguese', c.best_text, q.query,
                                   'MaxWords=30, MinWords=12, ShortWord=3, MaxFragments=1, '
                                   'StartSel=«, StopSel=»') AS snippet
                FROM clusters c, q
                WHERE c.rank >= $4
                ORDER BY c.rank * (0.5 + coalesce(c.score, 0))
                         * (CASE WHEN c.has_official THEN 1.2 ELSE 1.0 END) DESC
                LIMIT $3
                """,
                query,
                window_days,
                limit,
                min_rank,
            )

    async def event_info(self, cluster_id: str) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT cluster_id, max(relevance_score) AS score, "
                "max(coalesce((meta->'relevance'->>'publishers')::int, 1)) AS publishers, "
                "count(*) AS docs, (array_agg(title ORDER BY relevance_score DESC NULLS LAST))[1] "
                "AS title FROM documents WHERE cluster_id = $1 GROUP BY cluster_id",
                cluster_id,
            )

    async def cluster_documents(self, cluster_id: str, limit: int = 5) -> list[Document]:
        """Best sources of an event: official first, then most relevant, then longest."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source, doc_type, tier, url, title, published_at, author, content_text, "
                "pdf_url, extraction_level, status, meta FROM documents WHERE cluster_id = $1 "
                "AND url NOT ILIKE '%ao-vivo%' AND title NOT ILIKE '%ao vivo%' "
                "ORDER BY (tier = 'official') DESC, relevance_score DESC NULLS LAST, "
                "length(coalesce(content_text, '')) DESC LIMIT $2",
                cluster_id,
                limit,
            )
        return [Document(**{**dict(r), "meta": json.loads(r["meta"])}) for r in rows]

    async def get_anchors(
        self, cluster_id: str, docs_hash: str, prompt_version: str
    ) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT id, anchors, evidence, dropped FROM anchors "
                "WHERE cluster_id=$1 AND docs_hash=$2 AND prompt_version=$3",
                cluster_id,
                docs_hash,
                prompt_version,
            )

    async def save_anchors(
        self,
        cluster_id: str,
        docs_hash: str,
        prompt_version: str,
        anchors: dict,
        evidence: list,
        dropped: list,
        provider: str | None,
        model: str | None,
    ) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "INSERT INTO anchors (cluster_id, docs_hash, prompt_version, anchors, evidence, "
                "dropped, provider, model) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7,$8) "
                "ON CONFLICT (cluster_id, docs_hash, prompt_version) DO UPDATE SET "
                "anchors=EXCLUDED.anchors, evidence=EXCLUDED.evidence, dropped=EXCLUDED.dropped "
                "RETURNING id",
                cluster_id,
                docs_hash,
                prompt_version,
                json.dumps(anchors, ensure_ascii=False),
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(dropped, ensure_ascii=False),
                provider,
                model,
            )

    async def find_generation(
        self, cluster_id: str, fmt: str, level: str, prompt_versions: str
    ) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(
                "SELECT * FROM generations WHERE cluster_id=$1 AND fmt=$2 AND level=$3 "
                "AND prompt_versions=$4",
                cluster_id,
                fmt,
                level,
                prompt_versions,
            )

    async def generation_attempts(self, generation_id: int) -> list[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM generation_attempts WHERE generation_id=$1 ORDER BY n", generation_id
            )

    async def save_generation(self, row: dict, attempts: list[dict]) -> int:
        """Insert (or replace, on --force) a generation and all its attempts atomically."""
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM generations WHERE cluster_id=$1 AND fmt=$2 AND level=$3 "
                "AND prompt_versions=$4",
                row["cluster_id"],
                row["fmt"],
                row["level"],
                row["prompt_versions"],
            )
            gen_id = await conn.fetchval(
                "INSERT INTO generations (cluster_id, event_title, fmt, level, prompt_versions, "
                "anchors_id, content, eval, passed, score, attempts, best_attempt, latency_ms, "
                "topic) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13,$14) "
                "RETURNING id",
                row["cluster_id"],
                row["event_title"],
                row["fmt"],
                row["level"],
                row["prompt_versions"],
                row["anchors_id"],
                json.dumps(row["content"], ensure_ascii=False),
                json.dumps(row["eval"], ensure_ascii=False, default=str),
                row["passed"],
                row["score"],
                row["attempts"],
                row["best_attempt"],
                row["latency_ms"],
                row.get("topic"),
            )
            await conn.executemany(
                "INSERT INTO generation_attempts (generation_id, n, content, eval, provider, "
                "model, latency_ms) VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6,$7)",
                [
                    (
                        gen_id,
                        a["n"],
                        json.dumps(a["content"], ensure_ascii=False),
                        json.dumps(a["eval"], ensure_ascii=False, default=str),
                        a.get("provider"),
                        a.get("model"),
                        a.get("latency_ms"),
                    )
                    for a in attempts
                ],
            )
        return gen_id

    # ------------------------------------------------------------------ market series

    async def last_series_dates(self) -> dict[int, date]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT series_code, max(ref_date) AS d FROM market_series GROUP BY series_code"
            )
        return {r["series_code"]: r["d"] for r in rows}

    async def upsert_series(self, rows: Iterable[tuple[int, str, date, Decimal]]) -> int:
        data = list(rows)
        if not data:
            return 0
        async with self.pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO market_series (series_code, series_name, ref_date, value) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT (series_code, ref_date) DO UPDATE SET "
                "value = EXCLUDED.value WHERE market_series.value IS DISTINCT FROM EXCLUDED.value",
                data,
            )
        return len(data)

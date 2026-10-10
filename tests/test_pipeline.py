"""End-to-end (offline): all sources through the pipeline into Postgres, twice."""

from datetime import UTC, datetime

import httpx
import pytest

from scraper.pipeline import Pipeline, RunOptions
from scraper.sources.registry import FeedConfig, Registry
from tests.helpers import FIXTURES, fixture_client

pytestmark = pytest.mark.db

SINCE = datetime(2026, 9, 15, tzinfo=UTC)


def etag_route(body: bytes, tag: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == tag:
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": tag})

    return handler


ROUTES = {
    r"/copom/atas\?": "bcb_copom/atas_list.json",
    r"atas_detalhes\?nro_reuniao=281": "bcb_copom/atas_281.json",
    r"atas_detalhes\?nro_reuniao=280": "bcb_copom/atas_280.json",
    r"/copom/comunicados\?": "bcb_copom/comunicados_list.json",
    r"comunicados_detalhes\?nro_reuniao=281": "bcb_copom/comunicados_281.json",
    r"ipe_cia_aberta_2026\.zip": etag_route(
        (FIXTURES / "cvm_ipe/ipe_sample.zip").read_bytes(), '"z"'
    ),
    r"rad\.cvm\.gov\.br": lambda r: httpx.Response(
        200, content=(FIXTURES / "cvm_ipe/fato_relevante.pdf").read_bytes()
    ),
    r"feed\.test/suno": etag_route((FIXTURES / "feeds/suno.xml").read_bytes(), '"s"'),
    r"sgs\.433/": "bcb_sgs/ipca_2026.json",
    r"sgs\.\d+/": (200, b"[]"),
}

REGISTRY = Registry(
    official={
        "bcb_copom": {"enabled": True},
        "cvm_ipe": {"enabled": True},
        "bcb_sgs": {"enabled": True},
    },
    feeds=[FeedConfig(name="suno", kind="rss", url="https://feed.test/suno")],
)


async def test_two_runs_second_is_incremental(db, settings):
    http, calls = fixture_client(settings, ROUTES)
    settings.enrich_workers = 0  # inline PDF parsing in tests
    settings.heal_enabled = False  # healing has its own tests; keep this one clock-independent
    async with http:
        pipeline = Pipeline(settings, REGISTRY, db=db, http=http)
        first = await pipeline.run(RunOptions(since=SINCE, max_pdfs=4))

        assert first.written > 0 and first.series_rows > 0
        assert first.enrich["pdf"] == 4 and first.enrich["deferred"] > 0
        async with db.pool.acquire() as conn:
            stored = await conn.fetchval("SELECT count(*) FROM documents")
            pending = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE status='pending_enrich'"
            )
            health = await conn.fetchval("SELECT count(*) FROM source_health")
        assert stored == first.written and pending == first.enrich["deferred"]
        async with db.pool.acquire() as conn:
            unscored = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE relevance_score IS NULL OR cluster_id IS NULL"
            )
            ata = await conn.fetchrow(
                "SELECT relevance_score, meta->'relevance' AS r FROM documents "
                "WHERE doc_type='copom_ata' ORDER BY published_at DESC LIMIT 1"
            )
        assert unscored == 0 and first.relevance.scored == stored
        assert ata["relevance_score"] > 0 and '"lexical"' in ata["r"]
        assert health == 4  # copom, cvm, suno, sgs

        calls.clear()
        second = await pipeline.run(RunOptions(since=SINCE, max_pdfs=100))

    by_source = {r.source: r for r in second.reports}
    assert by_source["suno"].status == "not_modified"
    assert by_source["cvm_ipe"].status == "not_modified"
    assert all(r.items_new == 0 for r in second.reports)
    assert not any("detalhes?nro_reuniao=28" in c and "comunicados" not in c for c in calls)
    # the PDF backlog left by run 1 is drained by run 2
    assert second.enrich["pdf"] == pending
    async with db.pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM documents WHERE status='pending_enrich'") == 0
        )
        assert await conn.fetchval("SELECT count(*) FROM documents") == stored

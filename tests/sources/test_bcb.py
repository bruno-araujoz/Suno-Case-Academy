from datetime import UTC, date, datetime

from scraper.sources.base import MemoryStateStore, SourceContext
from scraper.sources.bcb_copom import BcbCopomSource
from scraper.sources.bcb_sgs import fetch_series
from tests.helpers import fixture_client

SINCE = datetime(2026, 7, 1, tzinfo=UTC)
COPOM_ROUTES = {
    r"/copom/atas\?": "bcb_copom/atas_list.json",
    r"atas_detalhes\?nro_reuniao=281": "bcb_copom/atas_281.json",
    r"atas_detalhes\?nro_reuniao=280": "bcb_copom/atas_280.json",
    r"/copom/comunicados\?": "bcb_copom/comunicados_list.json",
    r"comunicados_detalhes\?nro_reuniao=281": "bcb_copom/comunicados_281.json",
}


async def collect(source):
    return [d async for d in source.collect()]


async def test_copom_yields_full_text_minutes_and_statements(settings):
    http, _ = fixture_client(settings, COPOM_ROUTES)
    async with http:
        source = BcbCopomSource(SourceContext(http=http, state=MemoryStateStore(), since=SINCE))
        docs = await collect(source)

    atas = [d for d in docs if d.doc_type == "copom_ata"]
    comunicados = [d for d in docs if d.doc_type == "copom_comunicado"]
    assert {d.meta["meeting"] for d in atas} == {281, 280}
    assert len(comunicados) == 1  # 280's detail is not recorded -> 404, counted but skipped

    ata = next(d for d in atas if d.meta["meeting"] == 281)
    assert ata.tier == "official" and ata.extraction_level == "api"
    assert ata.published_at.date() == date(2026, 9, 22)
    assert ata.pdf_url and ata.pdf_url.endswith(".pdf")
    assert len(ata.content_text) > 5000 and "<" not in ata.content_text[:200]
    assert source.report.status == "ok"


async def test_copom_skips_detail_fetch_for_known_documents(settings):
    http, calls = fixture_client(settings, COPOM_ROUTES)
    async with http:
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=SINCE)
        first_run = await collect(BcbCopomSource(ctx))
        ctx.known = {d.url_hash for d in first_run}
        calls.clear()
        second_run = await collect(BcbCopomSource(ctx))
    assert second_run == []
    # Stored docs are not fetched again; only the one that failed before (280, 404) is retried.
    detail_calls = [c for c in calls if "detalhes" in c]
    assert detail_calls == [c for c in detail_calls if "comunicados_detalhes?nro_reuniao=280" in c]
    assert len(detail_calls) == 1


async def test_copom_listing_failure_is_reported_not_raised(settings):
    http, _ = fixture_client(settings, {r"/copom/": (503, b"")})
    async with http:
        source = BcbCopomSource(SourceContext(http=http, state=MemoryStateStore(), since=SINCE))
        assert await collect(source) == []
    assert source.report.status == "failed" and source.report.http_status == 503


async def test_sgs_parses_rows_incrementally(settings):
    http, calls = fixture_client(
        settings, {r"sgs\.433/": "bcb_sgs/ipca_2026.json", r"sgs\.\d+/": (200, b"[]")}
    )
    async with http:
        rows, report = await fetch_series(
            http, datetime(2026, 1, 1, tzinfo=UTC), last_dates={432: date(2026, 10, 1)}
        )
    ipca = [r for r in rows if r[0] == 433]
    assert ipca[0][2] == date(2026, 1, 1) and len(ipca) >= 9
    assert report["status"] == "ok"
    assert any("sgs.432" in c and "dataInicial=02%2F10%2F2026" in c for c in calls)

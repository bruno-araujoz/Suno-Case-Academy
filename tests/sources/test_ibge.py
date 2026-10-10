from datetime import UTC, datetime

from scraper.core.models import parse_datetime
from scraper.sources.base import MemoryStateStore, SourceContext
from scraper.sources.ibge import IbgeSource
from tests.helpers import fixture_client


def test_br_datetime_with_time():
    assert parse_datetime("09/10/2026 09:00:00") == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


async def test_ibge_keeps_market_releases_and_skips_enrichment(settings):
    http, calls = fixture_client(settings, {r"api/v3/noticias": "ibge/releases_sep.json"})
    async with http:
        ctx = SourceContext(
            http=http, state=MemoryStateStore(), since=datetime(2026, 9, 1, tzinfo=UTC)
        )
        source = IbgeSource(ctx)
        docs = [d async for d in source.collect()]
    assert docs and all(d.doc_type == "ibge_release" and d.tier == "official" for d in docs)
    assert any("IPCA" in d.title for d in docs)
    assert source.report.items_seen > len(docs)  # non-market releases filtered out
    assert all(not d.needs_enrichment(settings.min_content_chars) for d in docs)
    assert "de=09-01-2026" in calls[0] and "tipo=release" in calls[0]

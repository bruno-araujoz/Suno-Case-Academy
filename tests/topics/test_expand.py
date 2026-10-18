"""On-demand topic search on WordPress portals: ingest, cluster, then find (no network)."""

import pytest

from scraper.sources.feed import search_url
from scraper.sources.registry import FeedConfig, Registry
from tests.helpers import fixture_client
from topics import service

pytestmark = pytest.mark.db

PORTAL = FeedConfig(
    name="infomoney", kind="wpjson", url="https://im.test/wp-json/wp/v2/posts", searchable=True
)
REGISTRY = Registry(feeds=[PORTAL, FeedConfig(name="exame", kind="rss", url="https://ex.test/f")])


def test_search_url_derivation():
    assert search_url(PORTAL) == "https://im.test/wp-json/wp/v2/posts"
    rss = FeedConfig(
        name="suno",
        kind="rss",
        url="https://s.test/noticias/feed/",
        homepage="https://s.test/noticias/",
        searchable=True,
    )
    assert search_url(rss) == "https://s.test/noticias/wp-json/wp/v2/posts"
    assert search_url(FeedConfig(name="x", kind="rss", url="https://x.test/f")) is None


async def test_expand_ingests_clusters_and_finds_topic(db, settings, monkeypatch):
    monkeypatch.setattr(service, "EXPAND_WINDOW_DAYS", 3650)  # fixture dates are fixed
    monkeypatch.setattr(service, "load_registry", lambda: REGISTRY)
    http, calls = fixture_client(settings, {r"im\.test/wp-json": "feeds/infomoney_wp.json"})
    async with http:
        local_only = await service.find_topic(db, http, "Santander proventos")
        assert local_only.events == [] and not local_only.expanded and calls == []

        results = await service.find_topic(
            db, http, "Santander proventos", expand=True, window_days=3650
        )
    assert results.expanded and results.fetched == 5
    assert results.portals == {"infomoney": "5 novos de 5"}
    assert "search=Santander+proventos" in calls[0]
    assert results.events and "Santander" in results.events[0]["title"]
    async with db.pool.acquire() as conn:  # stored and clustered (searchable from now on)
        assert (
            await conn.fetchval("SELECT count(*) FROM documents WHERE cluster_id IS NOT NULL") == 5
        )

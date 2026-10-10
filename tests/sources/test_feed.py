from datetime import UTC, datetime

import httpx

from scraper.sources.base import MemoryStateStore, SourceContext
from scraper.sources.feed import FeedSource
from scraper.sources.registry import FeedConfig, load_registry
from tests.helpers import FIXTURES, fixture_client

SINCE = datetime(2026, 9, 1, tzinfo=UTC)


def rss(name="suno", url="https://feed.test/rss"):
    return FeedConfig(name=name, kind="rss", url=url)


async def collect(source):
    return [d async for d in source.collect()]


async def test_registry_lists_verified_feeds():
    reg = load_registry()
    assert len(reg.feeds) == 10 and reg.official_enabled("bcb_copom")
    assert {c.name for c in reg.coverage} == {"google_news"}


async def test_rss_full_content_comes_from_the_feed(settings):
    http, _ = fixture_client(settings, {r"feed\.test": "feeds/suno.xml"})
    async with http:
        source = FeedSource(SourceContext(http=http, state=MemoryStateStore(), since=SINCE), rss())
        docs = await collect(source)
    assert len(docs) == 10 and source.report.items_valid == source.report.items_seen == 10
    assert all(d.extraction_level == "feed" and d.published_at.tzinfo for d in docs)
    assert sum(len(d.content_text or "") > 1000 for d in docs) >= 8  # no deep fetch needed


async def test_arc_feed_parses(settings):
    http, _ = fixture_client(settings, {r"feed\.test": "feeds/estadao_economia.xml"})
    async with http:
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=SINCE)
        docs = await collect(FeedSource(ctx, rss("estadao_economia")))
    assert len(docs) == 20


async def test_second_run_uses_conditional_get_and_gets_304(settings):
    body = (FIXTURES / "feeds/suno.xml").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": '"v1"'})

    http, _ = fixture_client(settings, {r"feed\.test": handler})
    async with http:
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=SINCE)
        assert len(await collect(FeedSource(ctx, rss()))) == 10
        second = FeedSource(ctx, rss())
        assert await collect(second) == []
    assert second.report.status == "not_modified"
    state = await ctx.state.get_state("suno", "feed")
    assert state.etag == '"v1"' and state.watermark is not None


async def test_since_filters_old_entries(settings):
    http, _ = fixture_client(settings, {r"feed\.test": "feeds/suno.xml"})
    async with http:
        future = datetime(2026, 10, 9, 20, tzinfo=UTC)
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=future)
        docs = await collect(FeedSource(ctx, rss()))
    assert docs and all(d.published_at >= future for d in docs)


async def test_html_error_page_is_reported_as_failed(settings):
    http, _ = fixture_client(
        settings, {r"feed\.test": (200, b"<html><body>Cloudflare</body></html>")}
    )
    async with http:
        source = FeedSource(SourceContext(http=http, state=MemoryStateStore(), since=SINCE), rss())
        docs = await collect(source)
    assert docs == [] and source.report.status == "failed"
    assert source.report.items_valid == 0


async def test_wordpress_rest_with_after_param_and_utc_dates(settings):
    http, calls = fixture_client(settings, {r"wp-json": "feeds/infomoney_wp.json"})
    cfg = FeedConfig(
        name="infomoney",
        kind="wpjson",
        url="https://im.test/wp-json/wp/v2/posts",
        params={"categories": 1},
    )
    async with http:
        source = FeedSource(SourceContext(http=http, state=MemoryStateStore(), since=SINCE), cfg)
        docs = await collect(source)
    assert len(docs) == 5
    assert "after=2026-09-01T00%3A00%3A00" in calls[0] and "categories=1" in calls[0]
    assert all(d.published_at.tzinfo is not None and d.meta.get("wp_id") for d in docs)
    assert all(len(d.content_text or "") > 500 for d in docs)


def test_clean_feed_text_detects_teasers_and_strips_boilerplate():
    from scraper.sources.feed import clean_feed_text

    text, teaser = clean_feed_text("Lead da matéria.\n\nLeia mais em: https://exame.com/x/")
    assert teaser and text == "Lead da matéria."
    text, teaser = clean_feed_text("Corpo.\nThe post Nobel appeared first on Seu Dinheiro.")
    assert not teaser and text == "Corpo."
    assert clean_feed_text("Resumo da notícia [...]")[1]
    assert clean_feed_text("Texto completo normal.") == ("Texto completo normal.", False)


async def test_exame_teasers_are_flagged_for_enrichment(settings):
    """Audit finding (2026-10-09): Exame items with only a lead passed as ready."""
    http, _ = fixture_client(settings, {r"feed\.test": "feeds/exame.xml"})
    async with http:
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=SINCE)
        docs = await collect(FeedSource(ctx, rss("exame")))
    teasers = [d for d in docs if d.meta.get("teaser")]
    assert teasers and all(d.needs_enrichment(settings.min_content_chars) for d in teasers)
    assert not any("Leia mais em" in (d.content_text or "") for d in docs)

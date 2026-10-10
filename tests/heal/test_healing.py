"""Self-healing demos: L0 detects, L2 rediscovers a feed (real E-Investidor case), L4 rebuilds
a CSS schema after a layout change (LLM mocked). Clock-independent: thresholds are derived
from the fixtures' own dates."""

from datetime import UTC, datetime

import pytest

from scraper.core.db import SourceState
from scraper.heal import schema as schema_mod
from scraper.heal.healer import Healer
from scraper.heal.health import diagnose
from scraper.heal.schema import apply_schema, listing_is_healthy, load_schema, save_schema
from scraper.pipeline import Pipeline, RunOptions
from scraper.sources.base import MemoryStateStore, SourceContext, SourceReport
from scraper.sources.feed import FeedSource
from scraper.sources.registry import FeedConfig, Registry
from tests.helpers import FIXTURES, fixture_client

STALE_NEWEST = datetime(2026, 5, 27, 21, 59, tzinfo=UTC)  # last item of the frozen feed
FRESH_NEWEST = datetime(2026, 10, 9, 20, 8, tzinfo=UTC)  # last item of the live feed

SCHEMA_V1 = {
    "name": "moneytimes",
    "baseSelector": "div.news-list div.news-item",
    "fields": [
        {"name": "title", "selector": "h2.news-item__title a", "type": "text"},
        {
            "name": "url",
            "selector": "h2.news-item__title a",
            "type": "attribute",
            "attribute": "href",
        },
        {"name": "date", "selector": "span.date", "type": "text"},
    ],
}
SCHEMA_V2 = {
    "name": "moneytimes",
    "baseSelector": "div.feed-grid div.card",
    "fields": [
        {"name": "title", "selector": "h2.card-headline a", "type": "text"},
        {"name": "url", "selector": "h2.card-headline a", "type": "attribute", "attribute": "href"},
        {"name": "date", "selector": "span.date", "type": "text"},
    ],
}


@pytest.fixture
def healing_settings(settings):
    # Midpoint between the two feeds' freshness: stale one is stale, live one is fresh — forever.
    now = datetime.now(UTC)
    settings.stale_feed_days = ((now - STALE_NEWEST) + (now - FRESH_NEWEST)).days / 2
    settings.enrich_workers = 0
    return settings


@pytest.fixture
def schema_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(schema_mod, "SCHEMA_DIR", tmp_path)
    return tmp_path


EINVESTIDOR = FeedConfig(
    name="einvestidor",
    kind="rss",
    url="https://einvestidor.test/feed/",
    homepage="https://einvestidor.test/",
)
EINVESTIDOR_ROUTES = {
    r"einvestidor\.test/feed/$": "heal/einvestidor_stale_feed.xml",
    r"einvestidor\.test/$": "heal/einvestidor_home_head.html",
    r"estadao\.com\.br/arc/.*/einvestidor": "heal/einvestidor_new_feed.xml",
}


def test_l0_flags_frozen_feed(healing_settings):
    report = SourceReport(source="x", status="ok", items_seen=8, newest_entry_at=STALE_NEWEST)
    problem = diagnose(report, healing_settings)
    assert problem and "feed parado" in problem.reason
    fresh = SourceReport(source="x", status="ok", items_seen=8, newest_entry_at=FRESH_NEWEST)
    assert diagnose(fresh, healing_settings) is None


async def test_l2_real_case_einvestidor_frozen_feed_is_rediscovered(healing_settings):
    """Real case found on 2026-10-09: /feed/ answers 200 but stopped in May; the homepage
    advertises a live Arc feed on estadao.com.br. Healed without any LLM."""
    registry = Registry(feeds=[EINVESTIDOR])
    http, calls = fixture_client(healing_settings, EINVESTIDOR_ROUTES)
    async with http:
        summary = await Pipeline(healing_settings, registry, http=http).run(
            RunOptions(since=datetime(2026, 5, 1, tzinfo=UTC), dry_run=True, enrich=False)
        )
    report = next(r for r in summary.reports if r.source == "einvestidor")
    assert report.status == "healed" and report.level == "L2"
    assert "feed parado" in report.error and "estadao.com.br/arc" in report.error
    assert report.newest_entry_at >= FRESH_NEWEST
    assert any("estadao.com.br/arc" in c for c in calls)
    assert summary.written > 8  # stale items + the live feed's items


async def test_l2_state_persists_so_next_run_goes_straight_to_new_feed(healing_settings):
    http, calls = fixture_client(healing_settings, EINVESTIDOR_ROUTES)
    async with http:
        ctx = SourceContext(
            http=http, state=MemoryStateStore(), since=datetime(2026, 5, 1, tzinfo=UTC)
        )
        source = FeedSource(ctx, EINVESTIDOR)
        _ = [d async for d in source.collect()]
        repaired = await Healer(ctx, healing_settings).heal(source)
        assert repaired is not None
        _ = [d async for d in repaired.collect()]
        calls.clear()
        _ = [d async for d in FeedSource(ctx, EINVESTIDOR).collect()]
    assert calls and all("estadao.com.br/arc" in c for c in calls)


LISTING = FeedConfig(
    name="moneytimes",
    kind="rss",
    url="https://mt.test/feed/",
    homepage="https://www.moneytimes.com.br/ultimas-noticias/",
)


def broken_listing_routes():
    return {r"moneytimes\.com\.br/ultimas-noticias/$": "heal/moneytimes_listing_v2_broken.html"}


async def preset_html_state(ctx):
    version = save_schema("moneytimes", SCHEMA_V1)
    await ctx.state.save_state(
        SourceState("moneytimes", "feed", LISTING.homepage, kind="html", schema_version=version)
    )


def test_schema_v1_matches_original_layout_and_fails_on_redesign():
    base = LISTING.homepage
    original = (FIXTURES / "heal/moneytimes_listing.html").read_text()
    broken = (FIXTURES / "heal/moneytimes_listing_v2_broken.html").read_text()
    assert listing_is_healthy(apply_schema(original, SCHEMA_V1, base), base)
    assert not listing_is_healthy(apply_schema(broken, SCHEMA_V1, base), base)
    assert listing_is_healthy(apply_schema(broken, SCHEMA_V2, base), base)


async def test_l4_regenerates_schema_after_layout_change(healing_settings, schema_dir):
    prompts = []

    async def fake_llm(html: str, url: str):
        prompts.append(url)
        return SCHEMA_V2

    http, _ = fixture_client(healing_settings, broken_listing_routes())
    async with http:
        ctx = SourceContext(
            http=http, state=MemoryStateStore(), since=datetime(2026, 1, 1, tzinfo=UTC)
        )
        await preset_html_state(ctx)
        source = FeedSource(ctx, LISTING)
        assert [d async for d in source.collect()] == []
        assert source.report.status == "failed" and "não casa mais" in source.report.error

        repaired = await Healer(ctx, healing_settings, generator=fake_llm).heal(source)
        assert repaired is not None and prompts == [LISTING.homepage]
        docs = [d async for d in repaired.collect()]

    assert repaired.report.status == "healed" and repaired.report.level == "L4"
    assert load_schema("moneytimes", 2) == SCHEMA_V2 and load_schema("moneytimes", 1) == SCHEMA_V1
    assert len(docs) >= 15
    assert all(d.status == "pending_enrich" and "moneytimes.com.br" in d.url for d in docs)
    assert all(d.meta["date_provisional"] for d in docs)  # "2 hora(s) atrás" is not a date


async def test_l4_never_saves_an_invalid_generated_schema(healing_settings, schema_dir):
    async def bad_llm(html: str, url: str):
        return {"baseSelector": "div.nao-existe", "fields": []}

    http, _ = fixture_client(healing_settings, broken_listing_routes())
    async with http:
        ctx = SourceContext(
            http=http, state=MemoryStateStore(), since=datetime(2026, 1, 1, tzinfo=UTC)
        )
        await preset_html_state(ctx)
        source = FeedSource(ctx, LISTING)
        _ = [d async for d in source.collect()]
        assert await Healer(ctx, healing_settings, generator=bad_llm).heal(source) is None
    assert source.report.status == "failed"
    assert "reparo automático sem sucesso" in source.report.error
    assert not (schema_dir / "moneytimes.v2.json").exists()


async def test_incremental_wordpress_with_nothing_new_is_not_a_problem(healing_settings):
    """Regression (live run 2026-10-09): `after=<watermark>` returning [] triggered a repair
    that switched InfoMoney from WP-JSON to the generic RSS feed."""
    cfg = FeedConfig(name="infomoney", kind="wpjson", url="https://im.test/wp-json/wp/v2/posts")
    http, calls = fixture_client(healing_settings, {r"wp-json": (200, b"[]")})
    async with http:
        ctx = SourceContext(
            http=http, state=MemoryStateStore(), since=datetime(2026, 1, 1, tzinfo=UTC)
        )
        await ctx.state.save_state(
            SourceState("infomoney", "feed", cfg.url, watermark=FRESH_NEWEST)
        )
        source = FeedSource(ctx, cfg)
        assert [d async for d in source.collect()] == []
        assert source.report.newest_entry_at == FRESH_NEWEST
        assert diagnose(source.report, healing_settings) is None
        assert await Healer(ctx, healing_settings).heal(source) is None
    assert len(calls) == 1  # no rediscovery requests

"""On-demand collection: TTL, advisory lock, time budget, healer cooldown."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from scraper.ondemand import due_sources, ensure_fresh
from scraper.pipeline import RunSummary
from scraper.sources.registry import Registry, load_registry, parse_duration

pytestmark = pytest.mark.db

REGISTRY = Registry(
    defaults={"feed_ttl": "15m", "coverage_ttl": "1h"},
    official={"bcb_copom": {"enabled": True, "ttl": "24h"}, "cvm_ipe": {"enabled": False}},
    feeds=[{"name": "suno", "kind": "rss", "url": "https://x.test/feed"}],
)


class FakePipeline:
    def __init__(self, delay: float = 0.0):
        self.delay, self.calls = delay, []

    async def run(self, opts):
        self.calls.append(opts)
        await asyncio.sleep(self.delay)
        return RunSummary(run_id="t")


def test_registry_ttls_and_defaults():
    ttls = REGISTRY.ttls()
    assert ttls == {"bcb_copom": timedelta(hours=24), "suno": timedelta(minutes=15)}
    real = load_registry().ttls()
    assert real["cvm_ipe"] == timedelta(hours=6) and real["google_news"] == timedelta(hours=1)
    assert parse_duration("2d") == timedelta(days=2)


def test_due_sources():
    now = datetime(2026, 10, 14, 12, tzinfo=UTC)
    checks = {"suno": now - timedelta(minutes=5), "bcb_copom": now - timedelta(hours=25)}
    assert due_sources(REGISTRY.ttls(), checks, now) == ["bcb_copom"]
    assert due_sources(REGISTRY.ttls(), {}, now) == ["bcb_copom", "suno"]


async def test_first_call_collects_second_is_fresh(db, settings):
    pipe = FakePipeline()
    first = await ensure_fresh(db, settings=settings, registry=REGISTRY, pipeline=pipe)
    assert first.ran and first.due == ["bcb_copom", "suno"]
    assert pipe.calls[0].only == {"bcb_copom", "suno"} and pipe.calls[0].enrich is False
    second = await ensure_fresh(db, settings=settings, registry=REGISTRY, pipeline=pipe)
    assert second.due == [] and not second.ran and len(pipe.calls) == 1


async def test_concurrent_requests_collect_once(db, settings):
    pipe = FakePipeline(delay=0.3)
    a, b = await asyncio.gather(
        ensure_fresh(db, settings=settings, registry=REGISTRY, pipeline=pipe),
        ensure_fresh(db, settings=settings, registry=REGISTRY, pipeline=pipe),
    )
    assert len(pipe.calls) == 1
    assert sorted([a.locked_by_other, b.locked_by_other]) == [False, True]


async def test_time_budget_returns_and_keeps_sources_due(db, settings):
    pipe = FakePipeline(delay=5)
    report = await ensure_fresh(
        db, settings=settings, registry=REGISTRY, pipeline=pipe, budget_s=0.2
    )
    assert report.timed_out and not report.ran and report.duration_s < 2
    assert await db.get_checks() == {}  # nothing marked: next request tries again


async def test_healer_cooldown_persists(db):
    until = datetime.now(UTC) + timedelta(hours=6)
    await db.set_heal_after("suno", until)
    assert (await db.get_heal_after("suno")) == until
    await db.mark_checked(["suno"], datetime.now(UTC))  # must not clobber heal_after
    assert (await db.get_heal_after("suno")) == until

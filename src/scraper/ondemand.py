"""On-demand collection: refresh only the sources whose TTL expired, when a user asks.

Replaces fixed-cadence polling. A request calls `ensure_fresh`, which:
- picks the sources past their `ttl` (sources.yaml);
- takes a Postgres advisory lock (a concurrent request just uses what is in the database);
- runs the incremental pipeline for those sources only, within a time budget;
- records `checked_at` and prunes old health rows.
Whatever does not finish within the budget is simply retried on the next request.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .core.config import Settings, get_settings
from .core.db import Database
from .core.http import HttpClient
from .core.logging import get_logger
from .pipeline import Pipeline, RunOptions, RunSummary
from .sources.registry import Registry, load_registry

log = get_logger("ondemand")

LOCK_KEY = 0x5C0_1EC7  # pg_advisory_lock key reserved for collection runs
HEALTH_RETENTION_DAYS = 30


@dataclass
class FreshnessReport:
    due: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)
    ran: bool = False
    locked_by_other: bool = False
    timed_out: bool = False
    duration_s: float = 0.0
    summary: RunSummary | None = None


def due_sources(
    ttls: dict[str, timedelta], checks: dict[str, datetime | None], now: datetime
) -> list[str]:
    return sorted(
        name
        for name, ttl in ttls.items()
        if (last := checks.get(name)) is None or now - last >= ttl
    )


async def ensure_fresh(
    db: Database,
    *,
    budget_s: float = 20.0,
    settings: Settings | None = None,
    registry: Registry | None = None,
    http: HttpClient | None = None,
    pipeline: Pipeline | None = None,
) -> FreshnessReport:
    settings = settings or get_settings()
    registry = registry or load_registry()
    now = datetime.now(UTC)
    report = FreshnessReport()
    started = time.perf_counter()

    ttls = registry.ttls()
    report.due = due_sources(ttls, await db.get_checks(), now)
    report.fresh = sorted(set(ttls) - set(report.due))
    if not report.due:
        return report

    async with db.pool.acquire() as conn:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            report.locked_by_other = True  # another request is collecting right now
            return report
        try:
            pipe = pipeline or Pipeline(settings, registry, db=db, http=http)
            opts = RunOptions(
                since=now - timedelta(days=settings.default_since_days),
                only=set(report.due),
                enrich=False,
            )
            try:
                report.summary = await asyncio.wait_for(pipe.run(opts), timeout=budget_s)
                report.ran = True
                await db.mark_checked(report.due, now)
            except TimeoutError:
                report.timed_out = True  # unchecked sources stay due for the next request
                log.warning("Coleta sob demanda excedeu %.0fs; seguindo com o banco.", budget_s)
            await db.prune_health(HEALTH_RETENTION_DAYS)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    report.duration_s = round(time.perf_counter() - started, 2)
    return report

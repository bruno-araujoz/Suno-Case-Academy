"""Self-healing L0: decide whether a source run looks broken."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..core.config import Settings
from ..sources.base import SourceReport

REPAIRABLE_HTTP = {0, 404, 410, 403, 401, 500, 502, 503}


@dataclass
class Problem:
    reason: str


def diagnose(
    report: SourceReport, settings: Settings, now: datetime | None = None
) -> Problem | None:
    now = now or datetime.now(UTC)
    if report.status == "failed":
        if report.http_status in REPAIRABLE_HTTP or "feed" in (report.error or ""):
            return Problem(report.error or f"HTTP {report.http_status}")
        return Problem(report.error or "falha")
    if report.status == "degraded":
        return Problem(report.error or "degradada")
    if report.status in ("ok", "not_modified") and report.newest_entry_at is not None:
        age = now - report.newest_entry_at
        if age > timedelta(days=settings.stale_feed_days):
            return Problem(f"feed parado: item mais novo é de {report.newest_entry_at:%Y-%m-%d}")
    if report.status == "ok" and report.items_seen == 0 and report.newest_entry_at is None:
        return Problem("feed sem entradas")  # nothing now and no freshness reference at all
    return None

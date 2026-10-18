"""Find events for a free-text topic: local full-text search first, then (optionally) an
on-demand search on the WordPress portals, ingested and clustered before searching again."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from scraper.core.config import Settings, get_settings
from scraper.core.db import Database
from scraper.core.http import HttpClient
from scraper.core.logging import get_logger
from scraper.relevance.stage import RelevanceStage
from scraper.sources.base import SourceContext
from scraper.sources.feed import search_wpjson
from scraper.sources.registry import Registry, load_registry

log = get_logger("topics")

MIN_RESULTS = 2
EXPAND_BUDGET_S = 8.0
EXPAND_WINDOW_DAYS = 14


@dataclass
class TopicResults:
    query: str
    events: list[dict[str, Any]] = field(default_factory=list)
    expanded: bool = False
    fetched: int = 0  # documents brought from the portals
    portals: dict[str, str] = field(default_factory=dict)  # portal → status
    duration_ms: int = 0


def _card(row: Any) -> dict[str, Any]:
    data = dict(row)
    for key in ("last_at",):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    for key in ("score", "rank"):
        if data.get(key) is not None:
            data[key] = round(float(data[key]), 4)
    return data


async def expand_from_portals(
    db: Database,
    http: HttpClient,
    query: str,
    settings: Settings | None = None,
    registry: Registry | None = None,
) -> tuple[int, dict[str, str]]:
    """Search the searchable portals in parallel, store new documents and cluster them."""
    settings = settings or get_settings()
    registry = registry or load_registry()
    portals = [f for f in registry.feeds if f.enabled and f.searchable]
    since = datetime.now(UTC) - timedelta(days=EXPAND_WINDOW_DAYS)
    known = await db.known_url_hashes(since)
    ctx = SourceContext(http=http, state=db, since=since, known=known, settings=settings)
    results = await asyncio.wait_for(
        asyncio.gather(*(search_wpjson(ctx, p, query) for p in portals), return_exceptions=True),
        timeout=EXPAND_BUDGET_S,
    )
    docs, status = [], {}
    for portal, res in zip(portals, results, strict=True):
        if isinstance(res, BaseException):
            status[portal.name] = f"erro: {type(res).__name__}"
            continue
        found, report = res
        status[portal.name] = (
            f"{len(found)} novos de {report.items_seen}"
            if report.status != "failed"
            else report.error or "falhou"
        )
        docs.extend(found)
    unique = {d.url_hash: d for d in docs}
    if not unique:
        return 0, status
    new_docs = list(unique.values())
    await db.upsert_documents(new_docs)
    stage = RelevanceStage(settings)  # cluster the new documents together with recent ones
    stage.observe(new_docs)
    await stage.finalize(db, coverage=[], write=True)
    return len(new_docs), status


async def find_topic(
    db: Database,
    http: HttpClient,
    query: str,
    *,
    expand: bool = False,
    limit: int = 8,
    window_days: int = 21,
) -> TopicResults:
    started = time.perf_counter()
    query = query.strip()
    out = TopicResults(query=query)
    if len(query) < 2:
        return out
    rows = await db.search_events(query, window_days=window_days, limit=limit)
    if expand and len(rows) < MIN_RESULTS:
        try:
            out.fetched, out.portals = await expand_from_portals(db, http, query)
        except TimeoutError:
            out.portals = {"_": f"tempo esgotado ({EXPAND_BUDGET_S:.0f}s)"}
        out.expanded = True
        if out.fetched:
            rows = await db.search_events(query, window_days=window_days, limit=limit)
    out.events = [_card(r) for r in rows]
    out.duration_ms = int((time.perf_counter() - started) * 1000)
    return out

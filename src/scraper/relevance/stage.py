"""End-of-run relevance stage.

Scoring runs after all sources finished so every document sees the full coverage of its event
(documents from other portals in this run, recent ones already stored, Google News headlines).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..core.config import Settings
from ..core.db import Database
from ..core.models import Document
from ..sources.coverage import CoverageSignal, publisher_key
from .cluster import Clusterer, Item
from .scorer import lexical_score, score

PRELOAD_WINDOW = timedelta(days=7)


@dataclass
class _Record:
    key: str
    title: str
    publisher: str
    tier: str
    published_at: datetime
    lead: str
    lexical: float
    in_run: bool


@dataclass
class RelevanceStats:
    scored: int = 0
    clusters_multi_publisher: int = 0
    high_priority: int = 0
    coverage_signals: int = 0
    top: list[tuple[float, int, str, str]] = field(default_factory=list)  # score, pubs, src, title


class RelevanceStage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.records: dict[str, _Record] = {}

    def observe(self, docs: list[Document]) -> None:
        for d in docs:
            self.records[d.url_hash] = _Record(
                key=d.url_hash,
                title=d.title,
                publisher=publisher_key(d.source),
                tier=d.tier,
                published_at=d.published_at,
                lead=(d.content_text or "")[:300],
                lexical=lexical_score(d.title, d.content_text),
                in_run=True,
            )

    async def finalize(
        self, db: Database | None, coverage: list[CoverageSignal], write: bool
    ) -> RelevanceStats:
        stats = RelevanceStats(coverage_signals=len(coverage))
        now = datetime.now(UTC)
        records = dict(self.records)
        if db is not None:
            for r in await db.recent_for_clustering(now - PRELOAD_WINDOW):
                if r["url_hash"] not in records:
                    records[r["url_hash"]] = _Record(
                        key=r["url_hash"],
                        title=r["title"],
                        publisher=publisher_key(r["source"]),
                        tier=r["tier"],
                        published_at=r["published_at"],
                        lead=r["lead"] or "",
                        lexical=r["lexical"]
                        if r["lexical"] is not None
                        else lexical_score(r["title"], r["lead"]),
                        in_run=False,
                    )
        if not records:
            return stats

        clusterer = Clusterer()
        items = [
            Item(r.key, r.title, r.publisher, r.published_at, r.lead) for r in records.values()
        ]
        items += [
            Item(f"cov:{s.url_hash}", s.title, publisher_key(s.publisher), s.published_at or now)
            for s in coverage
        ]
        for item in sorted(items, key=lambda i: i.published_at):  # oldest first: stable ids
            clusterer.add(item)

        publishers: dict[str, set[str]] = {}
        touched: set[str] = set()
        for cid, items in clusterer.clusters().items():
            publishers[cid] = {i.publisher for i in items}
            if any(i.key in self.records or i.key.startswith("cov:") for i in items):
                touched.add(cid)
        stats.clusters_multi_publisher = sum(1 for p in publishers.values() if len(p) > 1)

        rows: list[tuple[str, str, float, str]] = []
        threshold = self.settings.high_priority_threshold
        for rec in records.values():
            cid = clusterer.cluster_of(rec.key)
            if not rec.in_run and cid not in touched:
                continue  # stored doc whose event got no new coverage: score unchanged
            n_pub = len(publishers[cid])
            b = score(
                self.settings,
                lexical=rec.lexical,
                tier=rec.tier,
                publishers=n_pub,
                published_at=rec.published_at,
                now=now,
            )
            high = b.score >= threshold
            stats.scored += 1
            stats.high_priority += high
            stats.top.append((b.score, n_pub, rec.publisher, rec.title))
            patch = {
                "relevance": {
                    "lexical": b.lexical,
                    "tier": b.tier,
                    "coverage": b.coverage,
                    "recency": b.recency,
                    "publishers": n_pub,
                },
                "high_priority": high,
            }
            rows.append((rec.key, cid, b.score, json.dumps(patch)))
        stats.top = sorted(stats.top, reverse=True)[:10]

        if db is not None and write:
            await db.update_relevance(rows)
            await db.upsert_coverage(
                [
                    (
                        s.url_hash,
                        s.publisher,
                        s.title,
                        s.url,
                        s.published_at,
                        clusterer.cluster_of(f"cov:{s.url_hash}"),
                    )
                    for s in coverage
                ]
            )
        return stats

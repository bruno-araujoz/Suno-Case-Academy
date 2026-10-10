"""Streaming pipeline: sources → dedupe → (enrich) → score → batch writer.

Single process, bounded asyncio queues (backpressure), one shared HTTP client. Items that
already carry full text (APIs, most feeds) go straight to the writer; only PDFs and
truncated items pay for an extra request. Nothing here calls an LLM.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .core.config import Settings, get_settings
from .core.db import Database
from .core.http import HttpClient
from .core.logging import get_logger
from .core.models import Document
from .enrich.enricher import Enricher
from .enrich.pool import CpuPool
from .heal.healer import Healer
from .heal.schema import SchemaGenerator, crawl4ai_generator
from .relevance.stage import RelevanceStage, RelevanceStats
from .sources.base import MemoryStateStore, Source, SourceContext, SourceReport
from .sources.bcb_copom import BcbCopomSource
from .sources.bcb_sgs import fetch_series
from .sources.coverage import CoverageSignal, google_news
from .sources.cvm_ipe import CvmIpeSource
from .sources.feed import FeedSource
from .sources.ibge import IbgeSource
from .sources.registry import Registry, load_registry

log = get_logger("pipeline")

_DONE = object()


@dataclass
class RunOptions:
    since: datetime
    only: set[str] | None = None
    dry_run: bool = False
    enrich: bool = True
    max_pdfs: int | None = None  # overrides sources.yaml cvm_ipe.max_pdfs_per_run


@dataclass
class RunSummary:
    run_id: str
    reports: list[SourceReport] = field(default_factory=list)
    written: int = 0
    skipped_duplicates: int = 0
    by_level: Counter = field(default_factory=Counter)
    by_status: Counter = field(default_factory=Counter)
    enrich: dict[str, int] = field(default_factory=dict)
    series_rows: int = 0
    relevance: RelevanceStats | None = None
    duration_s: float = 0.0
    sample: list[Document] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        settings: Settings | None = None,
        registry: Registry | None = None,
        *,
        db: Database | None = None,
        http: HttpClient | None = None,
        schema_generator: SchemaGenerator | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.registry = registry or load_registry()
        self.db = db
        self._http = http
        self.schema_generator = schema_generator

    # ------------------------------------------------------------------ source selection

    def build_sources(self, ctx: SourceContext, only: set[str] | None) -> list[Source]:
        def wanted(name: str) -> bool:
            return only is None or name in only

        sources: list[Source] = []
        if self.registry.official_enabled("bcb_copom") and wanted("bcb_copom"):
            sources.append(BcbCopomSource(ctx))
        if self.registry.official_enabled("cvm_ipe") and wanted("cvm_ipe"):
            sources.append(CvmIpeSource(ctx, self.registry.official.get("cvm_ipe")))
        if self.registry.official_enabled("ibge") and wanted("ibge"):
            sources.append(IbgeSource(ctx))
        for feed in self.registry.feeds:
            if feed.enabled and wanted(feed.name):
                sources.append(FeedSource(ctx, feed))
        return sources

    # ------------------------------------------------------------------ run

    async def run(self, opts: RunOptions) -> RunSummary:
        started = time.perf_counter()
        summary = RunSummary(run_id=datetime.now(UTC).strftime("%Y%m%dT%H%M%S"))
        http = self._http or HttpClient(self.settings)
        pool = CpuPool(self.settings.enrich_workers)
        try:
            state = self.db if (self.db and not opts.dry_run) else MemoryStateStore()
            known = await self.db.known_url_hashes(opts.since) if self.db else set()
            ctx = SourceContext(
                http=http, state=state, since=opts.since, known=known, settings=self.settings
            )
            sources = self.build_sources(ctx, opts.only)
            max_pdfs = opts.max_pdfs
            if max_pdfs is None:
                max_pdfs = self.registry.official.get("cvm_ipe", {}).get("max_pdfs_per_run")
            enricher = Enricher(http, pool, self.settings, max_pdfs=max_pdfs)
            healer = None
            if self.settings.heal_enabled:
                generator = self.schema_generator or crawl4ai_generator(self.settings)
                healer = Healer(ctx, self.settings, generator)

            relevance = RelevanceStage(self.settings)
            coverage: list[CoverageSignal] = []
            await asyncio.gather(
                self._stream(sources, ctx, enricher, healer, relevance, opts, summary),
                self._series(http, opts, summary),
                self._coverage(http, opts, summary, coverage),
            )
            write = self.db is not None and not opts.dry_run
            summary.relevance = await relevance.finalize(self.db, coverage, write)
            summary.enrich = vars(enricher.stats)
            summary.reports = [s.report for s in sources] + summary.reports
            await self._finish_health(summary, opts)
        finally:
            pool.close()
            if self._http is None:
                await http.aclose()
        summary.duration_s = round(time.perf_counter() - started, 2)
        return summary

    async def _stream(
        self,
        sources: list[Source],
        ctx: SourceContext,
        enricher: Enricher,
        healer: Healer | None,
        relevance: RelevanceStage,
        opts: RunOptions,
        summary: RunSummary,
    ) -> None:
        size = self.settings.queue_size
        incoming: asyncio.Queue = asyncio.Queue(size)
        to_enrich: asyncio.Queue = asyncio.Queue(size)
        to_write: asyncio.Queue = asyncio.Queue(size)
        seen_urls: set[str] = set(ctx.known)
        seen_content: set[str] = set()
        new_per_source: Counter = Counter()
        workers = max(2, self.settings.enrich_workers * 4)  # I/O bound: more than CPU workers

        async def produce(source: Source) -> None:
            async for doc in source.collect():
                await incoming.put(doc)
            if healer is not None and isinstance(source, FeedSource):
                repaired = await healer.heal(source)
                if repaired is not None:  # collect again with the repaired endpoint/schema
                    async for doc in repaired.collect():
                        await incoming.put(doc)
                    source.report = repaired.report

        async def producers() -> None:
            if self.db and opts.enrich and not opts.dry_run:
                # Backlog from previous runs: only what this run can process (PDF cap + a margin
                # for article retries), so deferred rows are not rewritten every run.
                cap = enricher.max_pdfs if enricher.max_pdfs is not None else 450
                for doc in await self.db.pending_documents(limit=cap + 50):
                    if opts.only is None or doc.source in opts.only:
                        await to_enrich.put(doc)
            await asyncio.gather(*(produce(s) for s in sources))
            await incoming.put(_DONE)

        async def gate() -> None:
            while (doc := await incoming.get()) is not _DONE:
                if doc.url_hash in seen_urls or (
                    doc.content_hash and doc.content_hash in seen_content
                ):
                    summary.skipped_duplicates += 1
                    continue
                seen_urls.add(doc.url_hash)
                if doc.content_hash:
                    seen_content.add(doc.content_hash)
                new_per_source[doc.source] += 1
                needs = doc.status == "pending_enrich" or doc.needs_enrichment(
                    self.settings.min_content_chars
                )
                if needs and opts.enrich:
                    await to_enrich.put(doc)
                else:  # with --no-enrich, pending docs are stored and enriched on a later run
                    await to_write.put(doc)
            for _ in range(workers):
                await to_enrich.put(_DONE)

        async def enrich_worker() -> None:
            while (doc := await to_enrich.get()) is not _DONE:
                await to_write.put(await enricher.enrich(doc))

        async def enrich_stage() -> None:
            await asyncio.gather(*(enrich_worker() for _ in range(workers)))
            await to_write.put(_DONE)

        async def writer() -> None:
            batch: list[Document] = []
            last_flush = time.monotonic()
            while True:
                try:
                    item = await asyncio.wait_for(
                        to_write.get(), timeout=self.settings.batch_flush_seconds
                    )
                except TimeoutError:
                    item = None
                if item is not None and item is not _DONE:
                    batch.append(item)
                due = time.monotonic() - last_flush >= self.settings.batch_flush_seconds
                if batch and (item is _DONE or len(batch) >= self.settings.batch_size or due):
                    relevance.observe(batch)
                    await self._flush(batch, opts, summary)
                    batch, last_flush = [], time.monotonic()
                if item is _DONE:
                    return

        await asyncio.gather(producers(), gate(), enrich_stage(), writer())
        for source in sources:
            source.report.items_new = new_per_source.get(source.name, 0)

    async def _flush(self, batch: list[Document], opts: RunOptions, summary: RunSummary) -> None:
        for doc in batch:
            summary.by_level[doc.extraction_level] += 1
            summary.by_status[doc.status] += 1
        if len(summary.sample) < 30:
            summary.sample.extend(batch[: 30 - len(summary.sample)])
        if self.db and not opts.dry_run:
            await self.db.upsert_documents(batch)
        summary.written += len(batch)

    async def _coverage(
        self, http: HttpClient, opts: RunOptions, summary: RunSummary, out: list[CoverageSignal]
    ) -> None:
        for config in self.registry.coverage:
            if not config.enabled or config.kind != "google_news":
                continue
            if opts.only is not None and config.name not in opts.only:
                continue
            signals, report = await google_news(http, config)
            out.extend(signals)
            summary.reports.append(
                SourceReport(
                    **{k: v for k, v in report.items() if k in SourceReport.__dataclass_fields__}
                )
            )

    async def _series(self, http: HttpClient, opts: RunOptions, summary: RunSummary) -> None:
        if not self.registry.official_enabled("bcb_sgs"):
            return
        if opts.only is not None and "bcb_sgs" not in opts.only:
            return
        last = await self.db.last_series_dates() if self.db else None
        rows, report = await fetch_series(http, opts.since, last)
        if self.db and not opts.dry_run:
            await self.db.upsert_series(rows)
        summary.series_rows = len(rows)
        summary.reports.append(
            SourceReport(
                **{k: v for k, v in report.items() if k in SourceReport.__dataclass_fields__}
            )
        )

    async def _finish_health(self, summary: RunSummary, opts: RunOptions) -> None:
        """L0: compare with each source's own baseline; record health rows."""
        for report in summary.reports:
            attempted = report.items_valid + report.items_invalid
            if report.status == "ok" and attempted >= 5 and report.items_invalid / attempted > 0.5:
                report.status = "degraded"
                report.error = f"{report.items_invalid}/{attempted} itens reprovados no contrato"
            elif (
                self.db
                and report.status == "ok"
                and report.items_seen == 0
                and report.newest_entry_at is None  # incremental "nothing new" is not drift
            ):
                baseline = await self.db.health_baseline(report.source)
                if baseline and baseline > 0:
                    report.status = "degraded"
                    report.error = f"0 entradas lidas (mediana recente: {baseline:g})"
            if self.db and not opts.dry_run:
                await self.db.record_health(summary.run_id, report.as_dict())

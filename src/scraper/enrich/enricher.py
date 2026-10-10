"""Fill `content_text` for documents that need it (PDF filings, truncated feed items)."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import Settings
from ..core.http import HttpClient
from ..core.logging import get_logger
from ..core.models import Document, html_to_text, parse_datetime
from ..core.robots import RobotsCache
from .article import extract_main_text, fetch_with_browser
from .pdf import pdf_to_text
from .pool import CpuPool

log = get_logger("enrich")

MAX_ATTEMPTS = 3


@dataclass
class EnrichStats:
    pdf: int = 0
    article: int = 0
    browser: int = 0
    deferred: int = 0
    failed: int = 0


class Enricher:
    def __init__(
        self, http: HttpClient, pool: CpuPool, settings: Settings, max_pdfs: int | None = None
    ) -> None:
        self.http = http
        self.pool = pool
        self.settings = settings
        self.max_pdfs = max_pdfs
        self.stats = EnrichStats()
        self._pdf_slots = 0  # reserved before the await, so concurrent workers respect the cap
        self.robots = RobotsCache(http)

    def _attempt(self, doc: Document) -> int:
        attempts = int(doc.meta.get("enrich_attempts", 0)) + 1
        doc.meta = {**doc.meta, "enrich_attempts": attempts}
        return attempts

    def _give_up_or_retry(self, doc: Document, attempts: int, reason: str) -> Document:
        # Keep whatever text we already have (e.g. a feed teaser) instead of losing the item.
        if attempts >= MAX_ATTEMPTS:
            doc.status = "ready" if doc.content_text else "failed"
            self.stats.failed += doc.status == "failed"
        else:
            doc.status = "pending_enrich"
        doc.meta = {**doc.meta, "enrich_error": reason}
        return doc

    async def enrich(self, doc: Document) -> Document:
        if doc.pdf_url:
            return await self._enrich_pdf(doc)
        return await self._enrich_article(doc)

    async def _enrich_pdf(self, doc: Document) -> Document:
        if self.max_pdfs is not None and self._pdf_slots >= self.max_pdfs:
            self.stats.deferred += 1
            doc.status = "pending_enrich"  # backlog: next run continues from here
            return doc
        self._pdf_slots += 1
        attempts = self._attempt(doc)
        result = await self.http.get(doc.pdf_url)
        if not result.ok:
            return self._give_up_or_retry(doc, attempts, result.error or "download falhou")
        if result.is_pdf:
            try:
                text = await self.pool.run(pdf_to_text, result.content)
            except Exception as exc:  # corrupt or encrypted PDF
                return self._give_up_or_retry(doc, attempts, f"pdf inválido: {exc}")
            level = "pdf"
        else:  # some filings are HTML pages
            text, level = html_to_text(result.text()), "article"
        if len(text) < 100:
            return self._give_up_or_retry(doc, attempts, "pdf sem texto (escaneado?)")
        self.stats.pdf += 1
        doc.content_text, doc.extraction_level, doc.status = text, level, "ready"
        return doc

    async def _enrich_article(self, doc: Document) -> Document:
        attempts = self._attempt(doc)
        if not await self.robots.allowed(doc.url):
            doc.meta = {**doc.meta, "enrich_error": "bloqueado por robots.txt"}
            doc.status = "ready" if doc.content_text else "failed"
            return doc
        result = await self.http.get(doc.url)
        text: str | None = None
        if result.ok:
            want_date = bool(doc.meta.get("date_provisional"))
            text, date = await self.pool.run(extract_main_text, result.text(), doc.url, want_date)
            if doc.meta.get("date_provisional") and (real := parse_datetime(date)):
                doc.published_at = real
                doc.meta = {**doc.meta, "date_provisional": False}
            if text and len(text) >= self.settings.min_content_chars:
                self.stats.article += 1
                doc.content_text, doc.extraction_level, doc.status = text, "article", "ready"
                return doc
        text = await fetch_with_browser(doc.url)
        if text and len(text) >= self.settings.min_content_chars:
            self.stats.browser += 1
            doc.content_text, doc.extraction_level, doc.status = text, "browser", "ready"
            return doc
        if doc.content_text:  # short but real feed text: accept rather than loop forever
            doc.status = "ready"
            return doc
        return self._give_up_or_retry(doc, attempts, result.error or "sem texto extraível")

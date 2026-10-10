"""Article text for items whose feed content is missing or truncated.

L3 of the repair ladder: trafilatura on the static HTML (fast, in the process pool) →
Crawl4AI headless browser (optional `browser` extra, only when trafilatura finds nothing).
"""

from __future__ import annotations

import asyncio

from ..core.logging import get_logger

log = get_logger("enrich.article")

BROWSER_TIMEOUT = 30.0
_browser_lock = asyncio.Semaphore(1)  # one headless browser at a time: it is heavy


def extract_main_text(
    html: str, url: str, want_date: bool = False
) -> tuple[str | None, str | None]:
    """(text, publication date) — runs inside the process pool.

    Metadata (date) is only requested when needed: htmldate's search can take seconds on pages
    without a date, so it runs with extensive_search disabled.
    """
    import json

    import trafilatura

    options = dict(url=url, include_comments=False, include_tables=True, favor_precision=True)
    if not want_date:
        return trafilatura.extract(html, **options), None
    raw = trafilatura.extract(
        html,
        **options,
        output_format="json",
        with_metadata=True,
        date_extraction_params={"extensive_search": False, "original_date": True},
    )
    if not raw:
        return None, None
    data = json.loads(raw)
    return data.get("text"), data.get("date")


def browser_available() -> bool:
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        return False
    return True


async def fetch_with_browser(url: str) -> str | None:
    """Render JS with Crawl4AI and return its markdown. None if unavailable or failed."""
    if not browser_available():
        return None
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

    async with _browser_lock:
        try:
            async with AsyncWebCrawler() as crawler:
                result = await asyncio.wait_for(
                    crawler.arun(url=url, config=CrawlerRunConfig()), timeout=BROWSER_TIMEOUT
                )
        except Exception as exc:  # timeout, browser crash, navigation error
            log.warning("Crawl4AI falhou em %s: %s", url, exc)
            return None
    markdown = getattr(result, "markdown", None)
    text = getattr(markdown, "fit_markdown", None) or getattr(markdown, "raw_markdown", None)
    return text or (str(markdown) if markdown else None)

import asyncio

import httpx

from scraper.core.models import Document
from scraper.enrich.enricher import MAX_ATTEMPTS, Enricher
from scraper.enrich.pool import CpuPool
from tests.helpers import FIXTURES, fixture_client

PDF = (FIXTURES / "cvm_ipe/fato_relevante.pdf").read_bytes()


def filing(i: int) -> Document:
    url = f"https://cvm.test/doc?p={i}"
    return Document(
        source="cvm_ipe",
        doc_type="fato_relevante",
        tier="official",
        url=url,
        pdf_url=url,
        title=f"Empresa {i} — Fato",
        published_at="2026-09-25",
        status="pending_enrich",
    )


async def test_pdf_cap_is_respected_under_concurrency(settings):
    http, _ = fixture_client(
        settings,
        {
            r"cvm\.test": lambda r: httpx.Response(
                200, content=PDF, headers={"Content-Type": "text/html"}
            )
        },
    )
    async with http:
        enricher = Enricher(http, CpuPool(0), settings, max_pdfs=3)
        docs = await asyncio.gather(*(enricher.enrich(filing(i)) for i in range(10)))
    assert sum(d.status == "ready" and d.extraction_level == "pdf" for d in docs) == 3
    assert sum(d.status == "pending_enrich" for d in docs) == 7
    assert enricher.stats.deferred == 7


async def test_failed_download_retries_then_fails(settings):
    http, _ = fixture_client(settings, {r"cvm\.test": (500, b"")})
    async with http:
        enricher = Enricher(http, CpuPool(0), settings)
        doc = filing(1)
        for _ in range(MAX_ATTEMPTS):
            doc = await enricher.enrich(doc)
    assert doc.status == "failed" and doc.meta["enrich_attempts"] == MAX_ATTEMPTS


async def test_truncated_feed_item_gets_article_text(settings):
    html = (
        "<html><body><article>"
        + "<p>O Copom manteve a Selic em 13,75% ao ano. " * 40
        + "</p></article></body></html>"
    )
    http, _ = fixture_client(settings, {r"portal\.test": (200, html.encode())})
    doc = Document(
        source="x",
        doc_type="news",
        tier="news",
        url="https://portal.test/n",
        title="Copom mantém Selic",
        published_at="2026-10-01",
        content_text="Resumo curto",
        extraction_level="feed",
    )
    async with http:
        out = await Enricher(http, CpuPool(0), settings).enrich(doc)
    assert out.extraction_level == "article" and len(out.content_text) > settings.min_content_chars

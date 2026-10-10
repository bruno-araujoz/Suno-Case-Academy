from datetime import UTC, datetime

import httpx

from scraper.sources.base import MemoryStateStore, SourceContext
from scraper.sources.cvm_ipe import CvmIpeSource, parse_ipe_zip, select_filings
from tests.helpers import FIXTURES, fixture_client

SINCE = datetime(2026, 9, 15, tzinfo=UTC)
ZIP = FIXTURES / "cvm_ipe/ipe_sample.zip"


def test_select_keeps_only_relevant_recent_latest_version():
    rows = parse_ipe_zip(ZIP.read_bytes())
    picked = select_filings(rows, SINCE, ("Fato Relevante",), ("Press-release",))
    assert picked
    assert all(r["Categoria"] == "Fato Relevante" or r["Tipo"] == "Press-release" for r in picked)
    assert all(r["Data_Entrega"] >= "2026-09-15" for r in picked)
    assert [r["Data_Entrega"] for r in picked] == sorted(
        (r["Data_Entrega"] for r in picked), reverse=True
    )

    dup = dict(picked[0], Versao="9", Assunto="versão nova")
    again = select_filings([*rows, dup], SINCE, ("Fato Relevante",), ("Press-release",))
    assert len(again) == len(picked)
    assert (
        next(r for r in again if r["Protocolo_Entrega"] == dup["Protocolo_Entrega"])["Versao"]
        == "9"
    )


async def test_source_emits_pending_pdf_documents_and_uses_etag(settings):
    body = ZIP.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"z1"':
            return httpx.Response(304)
        return httpx.Response(200, content=body, headers={"ETag": '"z1"'})

    http, calls = fixture_client(
        settings, {r"ipe_cia_aberta_2026\.zip": handler, r"ipe_cia_aberta_\d+\.zip": (404, b"")}
    )
    async with http:
        ctx = SourceContext(http=http, state=MemoryStateStore(), since=SINCE)
        source = CvmIpeSource(ctx)
        docs = [d async for d in source.collect()]
        assert docs
        assert {d.doc_type for d in docs} <= {"fato_relevante", "press_release"}
        assert all(d.status == "pending_enrich" and d.pdf_url == d.url for d in docs)
        assert all(d.meta["company"] and " — " in d.title for d in docs)

        again = CvmIpeSource(ctx)
        assert [d async for d in again.collect()] == []
        assert again.report.status == "not_modified"

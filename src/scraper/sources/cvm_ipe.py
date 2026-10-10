"""CVM — IPE open data: Fatos Relevantes and earnings Press-releases of all listed companies.

One yearly ZIP (≈2 MB, CSV latin-1, `;`) indexes every filing with a `Link_Download`. The ZIP
supports conditional GET, so an unchanged year costs one 304. Documents are emitted as
`pending_enrich` (the PDF is downloaded and parsed in the enrich stage).
Ficha: docs/sources/cvm_ipe.md
"""

from __future__ import annotations

import asyncio
import csv
import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from ..core.db import SourceState
from ..core.models import Document
from .base import Source, SourceContext

ZIP_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/ipe_cia_aberta_{year}.zip"
DEFAULT_CATEGORIES = ("Fato Relevante",)
DEFAULT_TYPES = ("Press-release",)


def parse_ipe_zip(data: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        with zf.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1"), delimiter=";")
            return list(reader)


def select_filings(
    rows: list[dict[str, str]], since: datetime, categories: tuple[str, ...], types: tuple[str, ...]
) -> list[dict[str, str]]:
    """Relevant categories, delivered since `since`, latest version per protocol, newest first."""
    since_str = since.astimezone(UTC).date().isoformat()
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("Categoria") not in categories and row.get("Tipo") not in types:
            continue
        if (row.get("Data_Entrega") or "") < since_str or not row.get("Link_Download"):
            continue
        protocol = row.get("Protocolo_Entrega") or row["Link_Download"]
        current = latest.get(protocol)
        if current is None or int(row.get("Versao") or 0) > int(current.get("Versao") or 0):
            latest[protocol] = row
    return sorted(latest.values(), key=lambda r: r.get("Data_Entrega", ""), reverse=True)


class CvmIpeSource(Source):
    name = "cvm_ipe"

    def __init__(self, ctx: SourceContext, options: dict[str, Any] | None = None) -> None:
        super().__init__(ctx)
        opts = options or {}
        self.categories = tuple(opts.get("categories") or DEFAULT_CATEGORIES)
        self.types = tuple(opts.get("types") or DEFAULT_TYPES)

    async def _collect(self) -> AsyncIterator[Document]:
        now = datetime.now(UTC)
        for year in range(self.ctx.since.year, now.year + 1):
            async for doc in self._collect_year(year):
                yield doc

    async def _collect_year(self, year: int) -> AsyncIterator[Document]:
        key = f"ipe_{year}"
        state = await self.ctx.state.get_state(self.name, key) or SourceState(
            self.name, key, ZIP_URL.format(year=year)
        )
        result = await self.ctx.http.get(
            state.endpoint, etag=state.etag, last_modified=state.last_modified
        )
        self.report.http_status = result.status
        if result.not_modified:
            if self.report.status == "ok":
                self.report.status = "not_modified"
            return
        if not result.ok:
            self.fail(result, f"zip {year}")
            return
        try:
            rows = await asyncio.to_thread(parse_ipe_zip, result.content)
        except (zipfile.BadZipFile, StopIteration, csv.Error) as exc:
            self.report.status = "failed"
            self.report.error = f"zip {year} inválido: {exc}"
            return
        if self.report.status == "not_modified":
            self.report.status = "ok"
        self.report.items_seen += len(rows)

        for row in select_filings(rows, self.ctx.since, self.categories, self.types):
            link = row["Link_Download"]
            if self.is_known(link):
                continue
            is_release = row.get("Tipo") in self.types
            subject = row.get("Assunto") or row.get("Tipo") or row.get("Categoria")
            doc = self.build(
                doc_type="press_release" if is_release else "fato_relevante",
                tier="official",
                url=link,
                pdf_url=link,
                title=f"{row.get('Nome_Companhia', '').strip()} — {subject}".strip(" —"),
                published_at=row.get("Data_Entrega"),
                status="pending_enrich",
                extraction_level="none",
                meta={
                    "company": row.get("Nome_Companhia"),
                    "cnpj": row.get("CNPJ_Companhia"),
                    "cvm_code": row.get("Codigo_CVM"),
                    "category": row.get("Categoria"),
                    "type": row.get("Tipo"),
                    "subject": row.get("Assunto"),
                    "reference_date": row.get("Data_Referencia"),
                    "protocol": row.get("Protocolo_Entrega"),
                    "version": row.get("Versao"),
                },
            )
            if doc:
                yield doc

        state.etag, state.last_modified = result.etag, result.last_modified
        await self.ctx.state.save_state(state)

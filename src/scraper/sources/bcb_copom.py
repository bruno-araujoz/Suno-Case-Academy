"""BCB — Copom minutes (atas) and statements (comunicados) via the site's JSON API.

The detail endpoints return the full text as HTML (`textoAta` / `textoComunicado`), so no PDF
parsing is needed. Note the key drift between endpoints (`nroReuniao` vs `nro_reuniao`).
Ficha: docs/sources/bcb_copom.md
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.models import Document, first, html_to_text, iter_items, parse_datetime
from .base import Source

BASE = "https://www.bcb.gov.br/api/servico/sitebcb/copom"
MEETING_KEYS = ("nroReuniao", "nro_reuniao", "numeroReuniao")
TITLE_KEYS = ("titulo", "title")
PUBLISHED_KEYS = ("dataPublicacao", "dataReferencia", "data")
MEETINGS_PER_YEAR = 8


@dataclass(frozen=True)
class _Kind:
    list_path: str
    detail_path: str
    doc_type: str
    text_keys: tuple[str, ...]


KINDS = (
    _Kind("atas", "atas_detalhes", "copom_ata", ("textoAta", "texto")),
    _Kind("comunicados", "comunicados_detalhes", "copom_comunicado", ("textoComunicado", "texto")),
)


class BcbCopomSource(Source):
    name = "bcb_copom"

    def _quantity(self) -> int:
        days = max(1, (datetime.now(UTC) - self.ctx.since).days)
        return min(300, days * MEETINGS_PER_YEAR // 365 + 2)

    async def _collect(self) -> AsyncIterator[Document]:
        for kind in KINDS:
            async for doc in self._collect_kind(kind):
                yield doc

    async def _collect_kind(self, kind: _Kind) -> AsyncIterator[Document]:
        listing = await self.ctx.http.get(
            f"{BASE}/{kind.list_path}", params={"quantidade": self._quantity()}
        )
        if not listing.ok:
            self.fail(listing, f"listagem {kind.list_path}")
            return
        self.report.http_status = listing.status

        pending = []
        for item in iter_items(listing.json()):
            self.report.items_seen += 1
            meeting = first(item, MEETING_KEYS)
            published = parse_datetime(first(item, PUBLISHED_KEYS))
            if meeting is None or published is None or published < self.ctx.since:
                continue
            detail_url = f"{BASE}/{kind.detail_path}?nro_reuniao={meeting}"
            if self.is_known(detail_url):
                continue
            pending.append((detail_url, item))

        # Details are independent: fetch concurrently (per-host limiter keeps it polite).
        results = await asyncio.gather(*(self.ctx.http.get(url) for url, _ in pending))
        for (detail_url, item), result in zip(pending, results, strict=True):
            if not result.ok:
                continue
            detail = (iter_items(result.json()) or [{}])[0]
            merged = {**item, **detail}
            doc = self.build(
                doc_type=kind.doc_type,
                tier="official",
                url=detail_url,
                title=first(merged, TITLE_KEYS),
                published_at=first(merged, PUBLISHED_KEYS),
                content_text=html_to_text(first(merged, kind.text_keys)),
                pdf_url=first(merged, ("urlPdfAta", "urlPdf")),
                extraction_level="api",
                meta={
                    "meeting": first(merged, MEETING_KEYS),
                    "reference_date": first(merged, ("dataReferencia",)),
                },
            )
            if doc:
                yield doc

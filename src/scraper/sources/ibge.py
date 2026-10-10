"""IBGE — official releases (IPCA, PIB, PNAD, indústria, varejo, serviços) via the news API.

The API gives title + a short introduction. The full page (agenciadenoticias.ibge.gov.br)
answers 403 to automated clients (checked 2026-10-09), so we do not try to enrich it: the
documents carry the official summary and the figures come from BCB SGS (market_series).
Ficha: docs/sources/ibge.md
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ..core.models import Document, first, iter_items
from ..relevance.text import fold
from .base import Source

URL = "https://servicodados.ibge.gov.br/api/v3/noticias/"
PAGE_SIZE = 100
MAX_PAGES = 10
# Releases that move markets; everything else (censo, geociências...) is skipped.
KEYWORDS = (
    "ipca",
    "inpc",
    "pib",
    "pnad",
    "desocupacao",
    "desemprego",
    "producao industrial",
    "industria",
    "varejo",
    "vendas no comercio",
    "servicos",
    "inflacao",
    "ipp",
)


class IbgeSource(Source):
    name = "ibge"

    async def _collect(self) -> AsyncIterator[Document]:
        since = self.ctx.since.strftime("%m-%d-%Y")  # API expects MM-DD-YYYY
        for page in range(1, MAX_PAGES + 1):
            result = await self.ctx.http.get(
                URL, params={"tipo": "release", "de": since, "qtd": PAGE_SIZE, "page": page}
            )
            self.report.http_status = result.status
            if not result.ok:
                self.fail(result, f"página {page}")
                return
            payload = result.json() or {}
            items = iter_items(payload)
            self.report.items_seen += len(items)
            for item in items:
                title = first(item, ("titulo", "title")) or ""
                link = first(item, ("link",))
                if not link or not any(k in fold(title) for k in KEYWORDS):
                    continue
                if self.is_known(str(link)):
                    continue
                doc = self.build(
                    doc_type="ibge_release",
                    tier="official",
                    url=link,
                    title=title,
                    published_at=first(item, ("data_publicacao",)),
                    content_text=first(item, ("introducao",)),
                    extraction_level="api",
                    meta={
                        "ibge_id": item.get("id"),
                        "product_id": item.get("produto_id"),
                        "no_enrich": True,
                        "note": "texto completo bloqueado (403) no site",
                    },
                )
                if doc:
                    yield doc
            if page >= int(payload.get("totalPages") or page):
                return

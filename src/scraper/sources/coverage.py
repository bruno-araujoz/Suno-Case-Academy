"""Coverage signals: headlines (no body) from Google News searches.

They only feed the relevance score — "how many different outlets cover this event" — and are
never treated as documents. The publisher comes from the title suffix ("... - CNN Brasil").
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

import xxhash

from ..core.http import HttpClient
from ..core.logging import get_logger
from ..core.models import canonical_url, parse_datetime
from ..relevance.text import fold
from .feed import parse_feed
from .registry import FeedConfig

log = get_logger("source.coverage")

GOOGLE_NEWS = "https://news.google.com/rss/search"
_SUFFIX = re.compile(r"^(?P<title>.+?)\s+-\s+(?P<publisher>[^-]{2,60})$")
_NON_ALNUM = re.compile(r"[^a-z0-9]")

# Same outlet under different names (Google News label vs our source name).
ALIASES = {
    "valoreconomico": "valor",
    "estadao": "estadao",
    "estadaoeconomia": "estadao",
    "einvestidor": "estadao",
    "bloomberglinea": "bloomberglinea",
    "bloomberglineabrasil": "bloomberglinea",
    "seudinheiro": "seudinheiro",
    "brazijournal": "braziljournal",
}


def publisher_key(name: str) -> str:
    key = _NON_ALNUM.sub("", fold(name).replace("_economia", ""))
    return ALIASES.get(key, key)


@dataclass
class CoverageSignal:
    publisher: str
    title: str
    url: str
    published_at: datetime | None

    @property
    def url_hash(self) -> str:
        return xxhash.xxh3_64_hexdigest(self.url)


async def google_news(http: HttpClient, config: FeedConfig) -> tuple[list[CoverageSignal], dict]:
    report = {"source": config.name, "status": "ok", "items_seen": 0, "items_valid": 0}

    async def one(query: str) -> list[CoverageSignal]:
        result = await http.get(
            GOOGLE_NEWS,
            params={
                "q": f"{query} when:{config.window}",
                "hl": "pt-BR",
                "gl": "BR",
                "ceid": "BR:pt-419",
            },
        )
        entries = parse_feed(result) if result.ok else None
        if entries is None:
            report["status"] = "degraded"
            report["error"] = f"consulta '{query}': {result.error or 'feed inválido'}"
            return []
        out = []
        for e in entries:
            report["items_seen"] += 1
            match = _SUFFIX.match((e.get("title") or "").strip())
            if not match or not e.get("link"):
                continue
            try:
                url = canonical_url(e["link"])
            except ValueError:
                continue
            out.append(
                CoverageSignal(
                    publisher=match["publisher"].strip(),
                    title=match["title"].strip(),
                    url=url,
                    published_at=parse_datetime(e.get("published")),
                )
            )
        return out

    batches = await asyncio.gather(*(one(q) for q in config.queries))
    unique = {s.url_hash: s for batch in batches for s in batch}
    report["items_valid"] = len(unique)
    return list(unique.values()), report

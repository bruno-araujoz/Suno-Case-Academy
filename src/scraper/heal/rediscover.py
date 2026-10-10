"""Self-healing L2: find a working feed endpoint again — no LLM.

Candidates, in order of trust: feeds the homepage advertises (<link rel="alternate">),
WordPress REST API (if the site is WordPress), then common feed paths. A candidate only wins
if it parses, has enough entries with title+link, and is fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit

import fastfeedparser
from selectolax.lexbor import LexborHTMLParser

from ..core.config import Settings
from ..core.http import HttpClient
from ..core.logging import get_logger
from ..core.models import first, parse_datetime
from ..core.robots import RobotsCache

log = get_logger("heal.rediscover")

FEED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/rss",
    "text/xml",
)
COMMON_PATHS = ("feed/", "rss/", "rss.xml", "feed.xml", "atom.xml", "index.xml")
MIN_ENTRIES = 3


@dataclass
class Candidate:
    kind: str  # rss | wpjson
    url: str
    origin: str  # advertised | wordpress | common
    entries: int = 0
    newest: datetime | None = None


def home_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def advertised_feeds(html: str, base_url: str) -> list[str]:
    tree = LexborHTMLParser(html)
    urls = []
    for link in tree.css('link[rel="alternate"]'):
        kind = (link.attributes.get("type") or "").lower()
        href = link.attributes.get("href")
        if href and any(t in kind for t in FEED_TYPES):
            urls.append(urljoin(base_url, href))
    return urls


def looks_like_wordpress(html: str) -> bool:
    return "/wp-content/" in html or "/wp-json/" in html


def _entries(kind: str, content: bytes, payload: Any) -> list[tuple[str | None, str | None, Any]]:
    """(title, link, date) tuples for a candidate payload."""
    if kind == "wpjson":
        if not isinstance(payload, list):
            return []
        return [
            (
                first(p, ("title",)),
                first(p, ("link",)),
                f"{p['date_gmt']}+00:00" if p.get("date_gmt") else None,
            )
            for p in payload
            if isinstance(p, dict)
        ]
    try:
        parsed = fastfeedparser.parse(content)
    except Exception:
        return []
    return [
        (e.get("title"), e.get("link"), e.get("published") or e.get("updated"))
        for e in parsed.entries
    ]


async def evaluate(http: HttpClient, candidate: Candidate, settings: Settings) -> bool:
    params = (
        {"per_page": 20, "_fields": "date_gmt,link,title"} if candidate.kind == "wpjson" else None
    )
    result = await http.get(candidate.url, params=params)
    if not result.ok:
        return False
    rows = _entries(
        candidate.kind, result.content, result.json() if candidate.kind == "wpjson" else None
    )
    complete = [r for r in rows if r[0] and r[1]]
    dates = [d for r in complete if (d := parse_datetime(r[2]))]
    if len(complete) < MIN_ENTRIES or len(complete) / max(1, len(rows)) < 0.8 or not dates:
        return False
    candidate.entries, candidate.newest = len(complete), max(dates)
    return datetime.now(UTC) - candidate.newest <= timedelta(days=settings.stale_feed_days)


async def rediscover(
    http: HttpClient,
    robots: RobotsCache,
    homepage: str | None,
    current_url: str,
    settings: Settings,
) -> Candidate | None:
    home = homepage or home_of(current_url)
    candidates: list[Candidate] = []
    html = ""
    if await robots.allowed(home):
        page = await http.get(home)
        if page.ok:
            html = page.text()
            candidates += [Candidate("rss", u, "advertised") for u in advertised_feeds(html, home)]
    site_root = home_of(home)
    if looks_like_wordpress(html):
        candidates.append(
            Candidate("wpjson", urljoin(site_root, "wp-json/wp/v2/posts"), "wordpress")
        )
    for base in dict.fromkeys((home, site_root)):
        candidates += [Candidate("rss", urljoin(base, p), "common") for p in COMMON_PATHS]

    seen = {current_url}
    valid: list[Candidate] = []
    for cand in candidates:
        if cand.url in seen:
            continue
        seen.add(cand.url)
        if await evaluate(http, cand, settings):
            valid.append(cand)
            if cand.origin == "advertised":  # the site itself points to it: take it
                break
    if not valid:
        log.info("L2: nenhum endpoint válido para %s (%d candidatos)", home, len(seen) - 1)
        return None
    best = max(valid, key=lambda c: (c.origin == "advertised", c.newest, c.entries))
    log.info(
        "L2: novo endpoint %s (%s, %d itens, mais novo %s)",
        best.url,
        best.origin,
        best.entries,
        best.newest,
    )
    return best

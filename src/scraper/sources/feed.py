"""Generic news source: RSS/Atom/JSON Feed, WordPress REST API or an HTML listing + CSS schema.

One class covers every portal in sources.yaml. Incremental by design:
- conditional GET (ETag / Last-Modified) → a feed with nothing new costs one 304;
- WordPress: `after=<watermark>` + pagination, so backfills fetch only the needed window.

The endpoint and kind come from `source_state` when the healer has repaired the source
(L2: new feed URL/kind; L4: `html` kind with a versioned schema in schemas/).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import fastfeedparser

from ..core.db import SourceState
from ..core.http import FetchResult
from ..core.models import Document, first, html_to_text, parse_datetime
from .base import Source, SourceContext, SourceReport
from .registry import FeedConfig

WP_FIELDS = "id,date_gmt,modified_gmt,link,title,excerpt,content"
WP_PER_PAGE = 100  # WordPress maximum: fewer round trips
WP_MAX_PAGES = 20


# Trailing boilerplate added by feed generators (WordPress, portals). Removed before measuring.
_BOILERPLATE = (
    re.compile(r"\n*The post .{0,300}? appeared first on .{0,120}$", re.S | re.I),
    re.compile(r"\n*O post .{0,300}? apareceu primeiro em .{0,120}$", re.S | re.I),
)
# Markers that the feed only carries a teaser: the item must be enriched from the article.
_TEASER = re.compile(
    r"\n*(?:Leia mais em|Continue lendo|Leia a (?:íntegra|matéria completa))\s*:?\s*\S*\s*$"
    r"|\s*\[(?:…|\.\.\.|&hellip;)\]\s*$",
    re.I,
)


def clean_feed_text(text: str) -> tuple[str, bool]:
    """(text without boilerplate, is_teaser)."""
    for pattern in _BOILERPLATE:
        text = pattern.sub("", text)
    teaser = bool(_TEASER.search(text))
    if teaser:
        text = _TEASER.sub("", text)
    return text.strip(), teaser


def _entry_content(entry: dict[str, Any]) -> str | None:
    content = entry.get("content")
    if isinstance(content, list) and content:
        value = content[0].get("value") if isinstance(content[0], dict) else content[0]
        if value:
            return str(value)
    return entry.get("description") or entry.get("summary")


class FeedSource(Source):
    def __init__(self, ctx: SourceContext, config: FeedConfig, tier: str = "news") -> None:
        self.name = config.name
        super().__init__(ctx)
        self.config = config
        self.tier = tier
        self.repair: tuple[str, str] | None = None  # (level, description) when built by healer

    async def _collect(self) -> AsyncIterator[Document]:
        state = await self.ctx.state.get_state(self.name, "feed") or SourceState(
            self.name, "feed", self.config.url or ""
        )
        kind = state.kind or self.config.kind
        if kind == "wpjson":
            gen = self._collect_wpjson(state)
        elif kind == "html":
            gen = self._collect_html(state)
        else:
            gen = self._collect_rss(state)
        async for doc in gen:
            yield doc

        if self.report.newest_entry_at:
            state.watermark = self.report.newest_entry_at
        else:  # 304, or incremental WP query with nothing after the watermark: both normal
            self.report.newest_entry_at = state.watermark
        if self.repair and self.report.status in ("ok", "not_modified"):
            self.report.status, self.report.level = "healed", self.repair[0]
            self.report.error = self.repair[1]
        if self.report.status != "failed":
            await self.ctx.state.save_state(state)

    def _seen_date(self, published: datetime | None) -> None:
        if published and (
            self.report.newest_entry_at is None or published > self.report.newest_entry_at
        ):
            self.report.newest_entry_at = published

    # ------------------------------------------------------------------ RSS / Atom

    async def _collect_rss(self, state: SourceState) -> AsyncIterator[Document]:
        result = await self.ctx.http.get(
            state.endpoint, etag=state.etag, last_modified=state.last_modified
        )
        self.report.http_status = result.status
        if result.not_modified:
            self.report.status = "not_modified"
            return
        if not result.ok:
            self.fail(result, "feed")
            return
        entries = parse_feed(result)
        if entries is None:
            self.report.status = "failed"
            self.report.error = "feed inválido: conteúdo não é RSS/Atom"
            return
        state.etag, state.last_modified = result.etag, result.last_modified
        self.report.items_seen += len(entries)
        for entry in entries:
            doc = self._entry_to_doc(entry)
            if doc:
                yield doc

    def _entry_to_doc(self, entry: dict[str, Any]) -> Document | None:
        link = first(entry, ("link", "id"))
        published = parse_datetime(first(entry, ("published", "updated", "date")))
        self._seen_date(published)
        if not link or (published and published < self.ctx.since) or self.is_known(str(link)):
            return None
        text, teaser = clean_feed_text(html_to_text(_entry_content(entry)))
        return self.build(
            doc_type="news",
            tier=self.tier,
            url=link,
            title=first(entry, ("title",)),
            published_at=published,
            author=first(entry, ("author",)),
            content_text=text or None,
            extraction_level="feed",
            meta={"teaser": True} if teaser else {},
        )

    # ------------------------------------------------------------------ WordPress REST

    async def _collect_wpjson(self, state: SourceState) -> AsyncIterator[Document]:
        after = max(filter(None, [state.watermark, self.ctx.since]))
        params = {
            **self.config.params,
            "per_page": WP_PER_PAGE,
            "after": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "_fields": WP_FIELDS,
            "orderby": "date",
            "order": "desc",
        }
        for page in range(1, WP_MAX_PAGES + 1):
            result = await self.ctx.http.get(state.endpoint, params={**params, "page": page})
            self.report.http_status = result.status
            if result.status == 400 and page > 1:  # WordPress: page beyond the last one
                return
            if not result.ok:
                self.fail(result, f"wp-json página {page}")
                return
            posts = result.json()
            if not isinstance(posts, list):
                self.report.status = "failed"
                self.report.error = "feed inválido: wp-json não retornou lista"
                return
            self.report.items_seen += len(posts)
            for post in posts:
                doc = self._post_to_doc(post)
                if doc:
                    yield doc
            total_pages = int(result.headers.get("x-wp-totalpages", page) or page)
            if page >= total_pages or len(posts) < WP_PER_PAGE:
                return

    def _post_to_doc(self, post: dict[str, Any]) -> Document | None:
        link = first(post, ("link",))
        date_gmt = first(post, ("date_gmt",))
        # date_gmt is UTC without offset; make that explicit (naive would mean São Paulo).
        published = parse_datetime(f"{date_gmt}+00:00") if date_gmt else None
        self._seen_date(published)
        if not link or self.is_known(str(link)):
            return None
        return self.build(
            doc_type="news",
            tier=self.tier,
            url=link,
            title=first(post, ("title",)),
            published_at=published,
            content_text=html_to_text(first(post, ("content", "excerpt"))) or None,
            extraction_level="feed",
            meta={"wp_id": post.get("id")},
        )

    # ------------------------------------------------------------------ HTML listing (L4)

    async def _collect_html(self, state: SourceState) -> AsyncIterator[Document]:
        from ..heal.schema import apply_schema, listing_is_healthy, load_schema

        schema = load_schema(self.name, state.schema_version)
        if schema is None:
            self.report.status = "failed"
            self.report.error = f"schema v{state.schema_version} ausente em schemas/"
            return
        result = await self.ctx.http.get(state.endpoint)
        self.report.http_status = result.status
        if not result.ok:
            self.fail(result, "listagem html")
            return
        items = apply_schema(result.text(), schema, state.endpoint)
        self.report.items_seen += len(items)
        if not listing_is_healthy(items, state.endpoint):
            self.report.status = "failed"
            self.report.error = f"feed inválido: schema v{state.schema_version} não casa mais"
            return
        now = datetime.now(UTC)
        for item in items:
            published = parse_datetime(item.get("date"))
            self._seen_date(published or now)
            if not item.get("url") or self.is_known(str(item["url"])):
                continue
            doc = self.build(
                doc_type="news",
                tier=self.tier,
                url=item["url"],
                title=item.get("title"),
                # Listings often show no date: provisional, fixed from the article's metadata.
                published_at=published or now,
                extraction_level="none",
                status="pending_enrich",
                meta={
                    "date_provisional": published is None,
                    "schema_version": state.schema_version,
                },
            )
            if doc:
                yield doc


def parse_feed(result: FetchResult) -> list[dict[str, Any]] | None:
    try:
        return list(fastfeedparser.parse(result.content).entries)
    except Exception:  # malformed XML / not a feed (e.g. HTML error page)
        return None


def search_url(config: FeedConfig) -> str | None:
    """WordPress search endpoint of a portal (None if the portal is not searchable)."""
    if not config.searchable:
        return None
    if config.kind == "wpjson" and config.url:
        return config.url
    if config.homepage:
        return config.homepage.rstrip("/") + "/wp-json/wp/v2/posts"
    return None


async def search_wpjson(
    ctx: SourceContext, config: FeedConfig, query: str, per_page: int = 20
) -> tuple[list[Document], SourceReport]:
    """On-demand topic search on a WordPress portal (`?search=`), full text included.

    Does not touch the feed's watermark/state: it is a side lookup, not an incremental poll.
    """
    source = FeedSource(ctx, config)
    url = search_url(config)
    if url is None:
        source.report.status = "failed"
        source.report.error = "portal sem busca"
        return [], source.report
    params = {
        "search": query,
        "per_page": per_page,
        "_fields": WP_FIELDS,
        "after": ctx.since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    result = await ctx.http.get(url, params=params)
    source.report.http_status = result.status
    posts = result.json() if result.ok else None
    if not isinstance(posts, list):
        source.fail(result, "busca wp-json")
        return [], source.report
    source.report.items_seen = len(posts)
    docs = [d for post in posts if (d := source._post_to_doc(post))]
    return docs, source.report

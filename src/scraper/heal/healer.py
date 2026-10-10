"""Repair ladder for feed sources: L0 diagnose → L2 rediscover → L4 LLM schema for HTML."""

from __future__ import annotations

from ..core.config import Settings
from ..core.db import SourceState
from ..core.http import HttpClient
from ..core.logging import get_logger
from ..core.robots import RobotsCache
from ..sources.base import SourceContext
from ..sources.feed import FeedSource
from .health import diagnose
from .rediscover import home_of, rediscover
from .schema import SchemaGenerator, apply_schema, listing_is_healthy, save_schema

log = get_logger("heal")


class Healer:
    def __init__(
        self, ctx: SourceContext, settings: Settings, generator: SchemaGenerator | None = None
    ) -> None:
        self.ctx = ctx
        self.http: HttpClient = ctx.http
        self.settings = settings
        self.generator = generator
        self.robots = RobotsCache(ctx.http)

    async def heal(self, source: FeedSource) -> FeedSource | None:
        """Return a re-configured source ready to collect, or None if healthy/unrepairable."""
        problem = diagnose(source.report, self.settings)
        if problem is None:
            return None
        log.warning("%s com problema: %s — iniciando reparo", source.name, problem.reason)
        state = await self.ctx.state.get_state(source.name, "feed") or SourceState(
            source.name, "feed", source.config.url or ""
        )

        found = await rediscover(
            self.http, self.robots, source.config.homepage, state.endpoint, self.settings
        )
        if found:
            await self._switch(state, found.url, found.kind, state.schema_version)
            return self._healed(source, "L2", problem.reason, f"{found.kind} {found.url}")

        if self.settings.heal_llm_enabled and self.generator is not None:
            listing = source.config.homepage or home_of(state.endpoint)
            fixed = await self._l4(source.name, listing)
            if fixed is not None:
                await self._switch(state, listing, "html", fixed)
                return self._healed(source, "L4", problem.reason, f"schema v{fixed}")

        source.report.status = "degraded" if source.report.status != "failed" else "failed"
        source.report.error = f"{problem.reason} (reparo automático sem sucesso)"
        return None

    async def _l4(self, name: str, listing_url: str) -> int | None:
        if not await self.robots.allowed(listing_url):
            return None
        page = await self.http.get(listing_url)
        if not page.ok:
            return None
        html = page.text()
        schema = await self.generator(html, listing_url)  # type: ignore[misc]
        if not schema:
            return None
        items = apply_schema(html, schema, listing_url)
        if not listing_is_healthy(items, listing_url):  # never trust an unvalidated schema
            log.warning(
                "L4: schema gerado para %s reprovado no contrato (%d itens)", name, len(items)
            )
            return None
        return save_schema(name, schema)

    async def _switch(self, state: SourceState, url: str, kind: str, version: int) -> None:
        state.endpoint, state.kind, state.schema_version = url, kind, version
        state.etag = state.last_modified = None
        await self.ctx.state.save_state(state)

    def _healed(self, old: FeedSource, level: str, reason: str, detail: str) -> FeedSource:
        new = FeedSource(self.ctx, old.config, tier=old.tier)
        new.repair = (level, f"{reason} → {detail}")
        return new

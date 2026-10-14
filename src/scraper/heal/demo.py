"""Live self-healing demo (`scrape.py heal-demo`): breaks a real source on purpose and shows the
repair ladder working against the real site. Nothing is persisted: state lives in memory,
schemas go to a temporary directory, sources.yaml and the database are not touched.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..core.config import Settings
from ..core.db import SourceState
from ..core.http import HttpClient
from ..sources.base import MemoryStateStore, SourceContext
from ..sources.feed import FeedSource
from ..sources.registry import FeedConfig
from . import schema as schema_mod
from .healer import Healer
from .health import diagnose
from .schema import Schema, crawl4ai_generator, save_schema

MONEYTIMES_LISTING = "https://www.moneytimes.com.br/ultimas-noticias/"

# What the "old layout" schema looked like: selectors that no longer exist on the page.
OBSOLETE_SCHEMA: Schema = {
    "name": "moneytimes",
    "baseSelector": "ul.lista-noticias li.noticia",
    "fields": [
        {"name": "title", "selector": "h3.titulo a", "type": "text"},
        {"name": "url", "selector": "h3.titulo a", "type": "attribute", "attribute": "href"},
    ],
}
# Stand-in for the LLM when Crawl4AI/LLM keys are not available: the schema an LLM is expected
# to produce for the current layout (validated by the same contract as a real one).
SIMULATED_LLM_SCHEMA: Schema = {
    "name": "moneytimes",
    "baseSelector": "div.news-list div.news-item",
    "fields": [
        {"name": "title", "selector": "h2.news-item__title a", "type": "text"},
        {
            "name": "url",
            "selector": "h2.news-item__title a",
            "type": "attribute",
            "attribute": "href",
        },
        {"name": "date", "selector": "span.date", "type": "text"},
    ],
}

SCENARIOS = {
    "404": "URL do feed da Suno trocada por uma inexistente (HTTP 404) → L2",
    "stale": "Feed real do E-Investidor parado desde maio/2026 → L2",
    "html": "Listagem HTML do Money Times com schema de layout antigo → L4 (LLM)",
}


def _say(step: str, text: str) -> None:
    print(f"  {step:<6} {text}")


async def _run_ladder(
    ctx: SourceContext, settings: Settings, cfg: FeedConfig, generator=None
) -> None:
    started = time.perf_counter()
    source = FeedSource(ctx, cfg)
    docs = [d async for d in source.collect()]
    r = source.report
    _say(
        "coleta",
        f"status={r.status} http={r.http_status} lidos={r.items_seen} "
        f"válidos={len(docs)} erro={r.error or '-'}",
    )
    if r.newest_entry_at:
        _say("", f"item mais novo: {r.newest_entry_at:%Y-%m-%d %H:%M}Z")

    problem = diagnose(r, settings)
    if problem is None:
        _say("L0", "nenhum problema detectado — nada a reparar")
        return
    _say("L0", f"problema detectado: {problem.reason}")

    healer = Healer(ctx, settings, generator)
    repaired = await healer.heal(source)
    if repaired is None:
        _say("FALHA", source.report.error or "reparo sem sucesso")
        return
    level, detail = repaired.repair or ("?", "")
    _say(level, f"reparado: {detail.split(' → ', 1)[-1]}")

    new_docs = [d async for d in repaired.collect()]
    rr = repaired.report
    _say(
        "coleta",
        f"status={rr.status} nível={rr.level} lidos={rr.items_seen} válidos={len(new_docs)}",
    )
    for d in new_docs[:3]:
        _say("", f"• {d.published_at:%Y-%m-%d %H:%M}Z  {d.title[:80]}")
    state = await ctx.state.get_state(cfg.name, "feed")
    _say(
        "estado",
        f"endpoint={state.endpoint[:90]} kind={state.kind} schema_v={state.schema_version}",
    )
    _say("tempo", f"{time.perf_counter() - started:.1f}s")


async def run_demo(settings: Settings, scenarios: list[str]) -> int:
    since = datetime.now(UTC) - timedelta(days=200)
    async with HttpClient(settings) as http:
        for name in scenarios:
            print(f"\n=== Cenário '{name}': {SCENARIOS[name]} ===")
            ctx = SourceContext(http=http, state=MemoryStateStore(), since=since, settings=settings)
            if name == "404":
                cfg = FeedConfig(
                    name="suno",
                    kind="rss",
                    url="https://www.suno.com.br/noticias/feed-quebrado/",
                    homepage="https://www.suno.com.br/noticias/",
                )
                await _run_ladder(ctx, settings, cfg)
            elif name == "stale":
                cfg = FeedConfig(
                    name="einvestidor",
                    kind="rss",
                    url="https://einvestidor.estadao.com.br/feed/",
                    homepage="https://einvestidor.estadao.com.br/",
                )
                await _run_ladder(ctx, settings, cfg)
            elif name == "html":
                await _html_scenario(ctx, settings)
    return 0


async def _html_scenario(ctx: SourceContext, settings: Settings) -> None:
    original_dir = schema_mod.SCHEMA_DIR
    with tempfile.TemporaryDirectory(prefix="heal-demo-") as tmp:
        schema_mod.SCHEMA_DIR = Path(tmp)  # never touch the repository's schemas/
        try:
            version = save_schema("moneytimes", OBSOLETE_SCHEMA)
            await ctx.state.save_state(
                SourceState(
                    "moneytimes", "feed", MONEYTIMES_LISTING, kind="html", schema_version=version
                )
            )
            generator = crawl4ai_generator(settings)
            if generator is not None:
                _say("info", "gerador: Crawl4AI + cadeia de LLM (real)")
            else:
                _say(
                    "info",
                    "gerador: SIMULADO (instale o extra `browser` e configure uma "
                    "chave de LLM no .env para usar o real)",
                )

                async def generator(html: str, url: str) -> Schema:
                    return SIMULATED_LLM_SCHEMA

            cfg = FeedConfig(
                name="moneytimes", kind="html", url=MONEYTIMES_LISTING, homepage=MONEYTIMES_LISTING
            )
            await _run_ladder_l4_only(ctx, settings, cfg, generator)
            files = sorted(f for f in os.listdir(tmp) if f.endswith(".json"))
            _say("schemas", f"{files} (em diretório temporário, apagado ao final)")
        finally:
            schema_mod.SCHEMA_DIR = original_dir


async def _run_ladder_l4_only(ctx, settings, cfg, generator) -> None:
    # Money Times is WordPress and has a working feed, so L2 would (correctly) win. To show L4,
    # the demo disables rediscovery for this scenario only.
    from . import healer as healer_mod

    original = healer_mod.rediscover

    async def no_rediscovery(*_, **__):
        return None

    healer_mod.rediscover = no_rediscovery
    try:
        _say("info", "L2 desligado neste cenário (o site tem feed; queremos ver o L4)")
        await _run_ladder(ctx, settings, cfg, generator)
    finally:
        healer_mod.rediscover = original

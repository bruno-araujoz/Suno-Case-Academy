"""CLI do scraper Suno Content.

Exemplos:
  uv run python scrape.py run --dry-run --since 30d
  uv run python scrape.py run --source bcb_copom --source suno
  uv run python scrape.py run --watch 15m
  uv run python scrape.py backfill --source cvm_ipe --year 2025
  uv run python scrape.py health
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from datetime import UTC, datetime, timedelta

from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.logging import setup_logging
from scraper.pipeline import Pipeline, RunOptions, RunSummary

_DURATION = re.compile(r"^(\d+)([mhd])$")


def parse_duration(text: str) -> timedelta:
    match = _DURATION.match(text)
    if not match:
        raise argparse.ArgumentTypeError("use <n>m, <n>h ou <n>d (ex.: 15m, 90d)")
    value, unit = int(match.group(1)), match.group(2)
    return {"m": timedelta(minutes=value), "h": timedelta(hours=value), "d": timedelta(days=value)}[
        unit
    ]


def print_summary(summary: RunSummary, dry_run: bool) -> None:
    mode = " (dry-run: nada gravado)" if dry_run else ""
    print(f"\n=== Rodada {summary.run_id}{mode} — {summary.duration_s}s ===")
    print(
        f"{'fonte':18} {'status':13} {'lidos':>6} {'válidos':>8} {'novos':>6} "
        f"{'inválidos':>9} {'ms':>7}  erro"
    )
    for r in sorted(summary.reports, key=lambda r: r.source):
        print(
            f"{r.source:18} {r.status:13} {r.items_seen:6} {r.items_valid:8} {r.items_new:6} "
            f"{r.items_invalid:9} {r.duration_ms:7}  {r.error or ''}"
        )
    print(
        f"\ngravados: {summary.written} | duplicados ignorados: {summary.skipped_duplicates} | "
        f"séries SGS: {summary.series_rows}"
    )
    print(f"por nível: {dict(summary.by_level)} | por status: {dict(summary.by_status)}")
    print(f"enriquecimento: {summary.enrich}")
    rel = summary.relevance
    if rel and rel.scored:
        print(
            f"relevância: {rel.scored} pontuados | {rel.high_priority} high_priority | "
            f"{rel.clusters_multi_publisher} eventos com 2+ veículos | "
            f"{rel.coverage_signals} manchetes de cobertura"
        )
        print("top eventos:")
        for value, pubs, src, title in rel.top:
            print(f"  {value:.3f}  {pubs} veíc.  [{src}] {title[:80]}")
    if dry_run and summary.sample:
        print("\namostra:")
        for d in summary.sample[:15]:
            chars = len(d.content_text or "")
            print(
                f"  [{d.source}] {d.published_at:%Y-%m-%d %H:%M}Z {d.doc_type:16} "
                f"{d.extraction_level:7} {chars:6}c  {d.title[:70]}"
            )


async def cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    since = datetime.now(UTC) - (args.since or timedelta(days=settings.default_since_days))
    if getattr(args, "year", None):
        since = datetime(args.year, 1, 1, tzinfo=UTC)
    opts = RunOptions(
        since=since,
        only=set(args.source) if args.source else None,
        dry_run=args.dry_run,
        enrich=not args.no_enrich,
        max_pdfs=args.max_pdfs,
    )

    async def once() -> None:
        db = None
        if not args.dry_run:
            db = await Database(settings).connect()
            await db.migrate()
        try:
            summary = await Pipeline(settings, db=db).run(opts)
        finally:
            if db:
                await db.close()
        print_summary(summary, args.dry_run)

    if not args.watch:
        await once()
        return 0
    while True:
        await once()
        print(f"\npróxima rodada em {args.watch} (Ctrl+C para sair)")
        await asyncio.sleep(args.watch.total_seconds())


async def cmd_health(_: argparse.Namespace) -> int:
    async with Database(get_settings()) as db:
        await db.migrate()
        rows = await db.latest_health()
        async with db.pool.acquire() as conn:
            counts = {
                r["source"]: (r["n"], r["pending"])
                for r in await conn.fetch(
                    "SELECT source, count(*) n, count(*) FILTER (WHERE status <> 'ready') pending "
                    "FROM documents GROUP BY source"
                )
            }
    if not rows:
        print("Nenhuma rodada registrada ainda. Rode: uv run python scrape.py run")
        return 0
    print(
        f"{'fonte':18} {'status':13} {'nível':6} {'lidos':>6} {'novos':>6} {'docs':>6} "
        f"{'pend.':>5} {'última rodada':20} erro"
    )
    for r in rows:
        n, pending = counts.get(r["source"], (0, 0))
        print(
            f"{r['source']:18} {r['status']:13} {r['level'] or '-':6} {r['items_seen']:6} "
            f"{r['items_new']:6} {n:6} {pending:5} {r['run_at']:%Y-%m-%d %H:%M:%S}  "
            f"{r['error'] or ''}"
        )
    return 0


async def cmd_heal_demo(args: argparse.Namespace) -> int:
    from scraper.heal.demo import SCENARIOS, run_demo

    scenarios = args.scenario or list(SCENARIOS)
    print("Demonstração de self-healing ao vivo — nada é gravado (estado em memória).")
    return await run_demo(get_settings(), scenarios)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scrape.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_run_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", action="append", help="restringe a fonte(s) (repetível)")
        p.add_argument("--dry-run", action="store_true", help="não grava nada no banco")
        p.add_argument("--no-enrich", action="store_true", help="não baixa PDFs/artigos")
        p.add_argument("--max-pdfs", type=int, help="limite de PDFs nesta rodada")

    run = sub.add_parser("run", help="coleta incremental")
    add_run_args(run)
    run.add_argument("--since", type=parse_duration, help="janela (ex.: 30d); padrão 90d")
    run.add_argument("--watch", type=parse_duration, help="repete a cada intervalo (ex.: 15m)")
    run.set_defaults(func=cmd_run)

    backfill = sub.add_parser("backfill", help="carga histórica a partir de 1º de janeiro")
    add_run_args(backfill)
    backfill.add_argument("--year", type=int, required=True)
    backfill.set_defaults(func=cmd_run, since=None, watch=None)

    demo = sub.add_parser("heal-demo", help="quebra fontes reais de propósito e mostra o reparo")
    demo.add_argument(
        "--scenario",
        action="append",
        choices=["404", "stale", "html"],
        help="cenário (repetível); padrão: todos",
    )
    demo.set_defaults(func=cmd_heal_demo)

    health = sub.add_parser("health", help="saúde das fontes")
    health.set_defaults(func=cmd_health)

    args = parser.parse_args(argv)
    setup_logging()
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())

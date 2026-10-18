"""Avaliação em lote (entregáveis 2 e 6 do TAPI).

uv run python evaluate.py batch --events 3      # 3 eventos × 3 formatos × 3 níveis
uv run python evaluate.py batch --events 2 --force --judge
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from evals.batch import run_batch
from generation.schemas import LEVELS
from scraper.core.logging import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    batch = sub.add_parser("batch")
    batch.add_argument("--events", type=int, default=3)
    batch.add_argument("--window", type=int, default=72, help="janela de eventos (horas)")
    batch.add_argument("--force", action="store_true", help="ignora o cache de gerações")
    batch.add_argument("--judge", action="store_true", help="liga o juiz LLM")
    batch.add_argument(
        "--same-events-as",
        type=Path,
        help="report.json anterior: reusa os mesmos eventos (comparação controlada)",
    )
    batch.add_argument("--levels", nargs="+", choices=LEVELS, default=list(LEVELS))
    args = parser.parse_args()
    setup_logging("WARNING")
    out = asyncio.run(
        run_batch(
            args.events,
            force=args.force,
            use_judge=args.judge,
            window_hours=args.window,
            log=lambda m: print(m, flush=True),
            same_events_as=args.same_events_as,
            levels=tuple(args.levels),
        )
    )
    print(f"\nRelatório: {out / 'report.md'}")
    print((out / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

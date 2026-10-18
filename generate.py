"""CLI de geração: um conteúdo para um formato e um nível.

uv run python generate.py --format carrossel --level iniciante
uv run python generate.py --format artigo --level avancado --event <cluster_id> --force
uv run python generate.py --list-events
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from generation.graph import NoEventError
from generation.schemas import FORMATS, LEVELS
from generation.service import NODE_LABELS, generate
from llm.router import LLMError
from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.logging import setup_logging


def show_content(fmt: str, content: dict) -> None:
    if fmt == "carrossel":
        for i, s in enumerate(content["slides"], 1):
            print(
                f"\n  [{i}/{len(content['slides'])} · {s['papel']}] {s['titulo']}\n  {s['texto']}"
            )
        print(f"\n  Legenda: {content['legenda']}\n  {' '.join(content['hashtags'])}")
    elif fmt == "roteiro":
        print(f"\n  {content['titulo']}")
        for b in content["blocos"]:
            print(f"\n  {b['inicio_s']:>2}–{b['fim_s']:>2}s  🎬 {b['gancho_visual']}")
            print(f"         🗣 {b['fala']}")
    else:
        print(f"\n  # {content['titulo']}\n\n  {content['lead']}")
        for s in content["secoes"]:
            print(f"\n  ## {s['subtitulo']}\n  {s['texto']}")
        print(f"\n  {content['conclusao']}")


def show_report(result) -> None:
    verdict = "APROVADO" if result.passed else "REPROVADO"
    print(f"\n=== Avaliação ({verdict} · score {result.score}) ===")
    for c in result.eval["checks"]:
        mark = "✓" if c["passed"] else ("✗✗" if c["hard"] else "✗")
        print(f"  {mark} {c['name']:42} {str(c['value'])[:28]:28} alvo {c['target']}")
    if len(result.attempts) > 1:
        print("\n  Tentativas (reflection):")
        for a in result.attempts:
            fails = [c["name"] for c in a["eval"]["checks"] if not c["passed"]]
            print(
                f"   #{a['n']} score {a['score']} via {a.get('provider')} — falhas: {fails or '—'}"
            )
    print("\n  Fontes:")
    for e in result.evidence:
        print(f"   [{e['id']}] {e['source']} · {e['title'][:80]}\n        {e['url']}")
    if not result.glossary_reviewed:
        print("\n  ⚠ glossário ainda não revisado pelo time (glossary/candidates.yaml)")


async def main_async(args: argparse.Namespace) -> int:
    async with Database(get_settings()) as db:
        await db.migrate()
        if args.list_events:
            for e in await db.top_events(args.window):
                print(
                    f"{e['score'] or 0:.3f}  {e['publishers']} veíc.  {e['docs']} docs  "
                    f"{e['cluster_id']}  {e['title'][:80]}"
                )
            return 0

        def progress(node: str, update: dict) -> None:
            extra = ""
            if node == "select_event" and "event_title" in update:
                extra = f" → {update['event_title'][:70]} ({update.get('publishers')} veíc.)"
            elif node == "check_cache" and update.get("cached"):
                extra = " → resultado em cache (0 chamadas de LLM)"
            elif node == "evaluate" and update.get("evals"):
                e = update["evals"][-1]
                extra = f" → {'aprovado' if e['passed'] else 'reprovado'} (score {e['score']})"
            print(f"• {NODE_LABELS.get(node, node)}{extra}", flush=True)

        try:
            result = await generate(
                args.format,
                args.level,
                db=db,
                refresh=not args.no_refresh,
                force=args.force,
                use_judge=args.judge,
                event=args.event,
                on_progress=progress,
                demo_reflection=args.demo_reflection,
            )
        except (NoEventError, LLMError, ValueError) as exc:
            print(f"\nNão foi possível gerar: {exc}", file=sys.stderr)
            return 1
    if result.demo_reflection:
        print(
            "\n[modo demonstração] a 1ª tentativa foi escrita de propósito SEM adaptação ao "
            "público, para mostrar o avaliador reprovando e a reescrita corrigindo."
        )
    print(f"\n=== {args.format.upper()} · {args.level} · evento: {result.event_title} ===")
    show_content(result.fmt, result.content)
    show_report(result)
    print(
        f"\n  {'(cache) ' if result.cached else ''}tempo total {result.latency_ms / 1000:.1f}s · "
        f"geração #{result.generation_id}"
    )
    if args.json:
        print(json.dumps(result.content, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--format", choices=FORMATS, default="carrossel")
    p.add_argument("--level", choices=LEVELS, default="iniciante")
    p.add_argument("--event", help="cluster_id específico (veja --list-events)")
    p.add_argument("--no-refresh", action="store_true", help="não atualiza as fontes antes")
    p.add_argument("--force", action="store_true", help="ignora o cache e gera de novo")
    p.add_argument("--judge", action="store_true", help="liga o juiz LLM (afirmações sem número)")
    p.add_argument(
        "--demo-reflection",
        action="store_true",
        help="demonstração: 1ª escrita sem adaptação ao público → reprovada → reescrita",
    )
    p.add_argument("--list-events", action="store_true")
    p.add_argument("--window", type=int, default=48, help="janela de eventos (horas)")
    p.add_argument("--json", action="store_true", help="imprime o conteúdo em JSON")
    args = p.parse_args()
    setup_logging("WARNING")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())

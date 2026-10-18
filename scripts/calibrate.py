"""Calibrate level targets on real text (offline).

  uv run python scripts/calibrate.py corpus        # metric distributions per corpus group
  uv run python scripts/calibrate.py labeled       # agreement with the team-labeled set

Groups: official documents (≈ "avançado" register), portal news (≈ "intermediário").
There is no reliable published "beginner" corpus (Suno's educational guides scored *worse* than
news, Flesch 33–40), so the beginner target comes from Martins' scale plus the labeled set.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml

from evals.jargon import analyze
from evals.readability import readability
from glossary.matcher import load_glossary
from scraper.core.config import get_settings
from scraper.core.db import Database

LABELED = Path(__file__).resolve().parents[1] / "evals" / "labeled"


def pct(values: list[float], q: float) -> float:
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 2) if values else float("nan")


def describe(name: str, texts: list[str]) -> dict:
    g = load_glossary(True)
    flesch, adv, inter, unexpl = [], [], [], []
    for text in texts:
        r = readability(text[:6000])
        if r.flesch is None:
            continue
        j = analyze(text[:6000], g)
        flesch.append(r.flesch)
        adv.append(j.density("avancado"))
        inter.append(j.density("intermediario"))
        unexpl.append(len(j.unexplained.get("avancado", [])))
    row = {
        "grupo": name,
        "n": len(flesch),
        "flesch p10/p50/p90": (pct(flesch, 0.1), pct(flesch, 0.5), pct(flesch, 0.9)),
        "avançados/100 p10/p50/p90": (pct(adv, 0.1), pct(adv, 0.5), pct(adv, 0.9)),
        "intermediários/100 p50": pct(inter, 0.5),
        "avançados sem explicação p50": pct(unexpl, 0.5),
    }
    print(row)
    return row


async def corpus() -> None:
    async with Database(get_settings()) as db, db.pool.acquire() as conn:
        groups = {
            "atas Copom": "doc_type='copom_ata'",
            "comunicados Copom": "doc_type='copom_comunicado'",
            "fatos relevantes/releases": "doc_type IN ('fato_relevante','press_release')",
            "notícias (portais)": "tier='news'",
        }
        for name, where in groups.items():
            rows = await conn.fetch(
                f"SELECT content_text FROM documents WHERE {where} AND status='ready' "  # noqa: S608
                "AND length(content_text) > 800 ORDER BY random() LIMIT 400"
            )
            describe(name, [r["content_text"] for r in rows])


def labeled() -> None:
    files = sorted(LABELED.glob("*.yaml"))
    rows = [
        r
        for f in files
        for r in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])
        if r.get("texto") and r.get("nivel") and not r.get("exemplo")
    ]
    if not rows:
        sys.exit(f"Nenhum texto rotulado em {LABELED} (veja template.yaml).")
    for level in ("iniciante", "intermediario", "avancado"):
        describe(f"rotulado: {level}", [r["texto"] for r in rows if r["nivel"] == level])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "corpus"
    asyncio.run(corpus()) if cmd == "corpus" else labeled()

"""Build the layered glossary (offline). Runtime never calls these sources.

uv run python scripts/build_glossary.py seed-bcb        # 1x: BCB glossary API → sources/bcb.json
uv run python scripts/build_glossary.py mine            # corpus candidates → sources/corpus.json
uv run python scripts/build_glossary.py propose [--limit 400]   # LLM → candidates.yaml
uv run python scripts/build_glossary.py promote         # revisado: true → terms.yaml
uv run python scripts/build_glossary.py stats
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import re
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from glossary.matcher import GLOSSARY_DIR, Glossary, Term
from llm.prompts import load_prompt
from llm.router import LLMError, LLMRouter, db_recorder
from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.http import HttpClient
from scraper.core.models import html_to_text
from scraper.relevance.text import STOPWORDS, fold

SOURCES = GLOSSARY_DIR / "sources"
CANDIDATES = GLOSSARY_DIR / "candidates.yaml"
TERMS = GLOSSARY_DIR / "terms.yaml"
BCB_URL = "https://www.bcb.gov.br/api/servico/sitebcb/glossario"

# ------------------------------------------------------------------ seed: BCB


async def seed_bcb() -> None:
    async with HttpClient() as http:
        result = await http.get(BCB_URL, params={"quantidade": 3})
    if not result.ok:
        sys.exit(f"BCB respondeu {result.status}: {result.error}")
    items = (result.json() or {}).get("conteudo") or []
    rows = [
        {
            "termo": i["Termo"].strip(),
            "definicao": html_to_text(i.get("Descricao") or ""),
            "fonte": "bcb",
        }
        for i in items
        if i.get("Termo")
    ]
    SOURCES.mkdir(parents=True, exist_ok=True)
    (SOURCES / "bcb.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"BCB: {len(rows)} termos → {SOURCES / 'bcb.json'}")


# ------------------------------------------------------------------ mine: corpus keyness

_WORD = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]+")
_EN = {
    "the",
    "and",
    "of",
    "to",
    "in",
    "its",
    "with",
    "for",
    "on",
    "is",
    "that",
    "by",
    "which",
    "this",
    "be",
    "as",
    "at",
    "from",
    "company",
}
_PT = {
    "de",
    "da",
    "do",
    "que",
    "em",
    "para",
    "com",
    "os",
    "as",
    "no",
    "na",
    "uma",
    "por",
    "dos",
    "das",
    "ao",
    "se",
}
_NOISE = set(
    """art arts parágrafo parágrafos inciso incisos alínea cep nire cnpj cpf www http https
janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro
dez vinte trinta quarenta cinquenta sessenta setenta oitenta noventa cem mil milhões bilhões
segunda terça quarta quinta sexta sábado domingo ata reunião copom bcb cvm""".split()
)


def portuguese_paragraphs(text: str) -> str:
    keep = []
    for par in re.split(r"\n+", text):
        toks = [t.lower() for t in _WORD.findall(par)]
        if toks and sum(t in _PT for t in toks) > sum(t in _EN for t in toks):
            keep.append(par)
    return "\n".join(keep)


def ngrams(text: str) -> tuple[collections.Counter, collections.Counter]:
    """(counts by lowercase n-gram, counts of capitalized occurrences)."""
    toks = _WORD.findall(text)
    counts, caps = collections.Counter(), collections.Counter()
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            gram = toks[i : i + n]
            low = [t.lower() for t in gram]
            if fold(low[0]) in STOPWORDS or fold(low[-1]) in STOPWORDS:
                continue
            if any(fold(t) in _NOISE for t in low) or min(len(low[0]), len(low[-1])) < 3:
                continue
            key = " ".join(low)
            counts[key] += 1
            if gram[0][0].isupper() and i > 0 and not toks[i - 1].endswith("."):
                caps[key] += 1
    return counts, caps


async def mine(limit: int) -> None:
    from wordfreq import zipf_frequency

    async with Database(get_settings()) as db, db.pool.acquire() as conn:
        official = [
            r["content_text"]
            for r in await conn.fetch(
                "SELECT content_text FROM documents WHERE tier='official' AND status='ready' "
                "AND length(content_text) > 500"
            )
        ]
        news = [
            r["content_text"]
            for r in await conn.fetch(
                "SELECT content_text FROM documents WHERE tier='news' AND status='ready' "
                "ORDER BY random() LIMIT 3000"
            )
        ]
    A, caps, DF = collections.Counter(), collections.Counter(), collections.Counter()
    for text in official:
        counts, capitalized = ngrams(portuguese_paragraphs(text))
        A.update(counts)
        caps.update(capitalized)
        DF.update(set(counts))
    B, DFB = collections.Counter(), collections.Counter()
    for text in news:
        counts, _ = ngrams(text)
        B.update(counts)
        DFB.update(set(counts))
    na, nb = sum(A.values()), sum(B.values())
    out = []
    for gram, fa in A.items():
        if fa < 6 or DF[gram] < 3 or DF[gram] > 0.25 * len(official):
            continue  # rare / boilerplate
        if caps[gram] / fa > 0.6:
            continue  # mostly capitalized mid-sentence → proper noun
        if " " not in gram and zipf_frequency(gram, "pt") > 4.0:
            continue  # common Portuguese word
        fb = B.get(gram, 0)
        lo = math.log((fa + 0.5) / (na - fa + 0.5)) - math.log((fb + 0.5) / (nb - fb + 0.5))
        out.append(
            {
                "termo": gram,
                "log_odds": round(lo, 3),
                "freq_oficial": fa,
                "docs_oficiais": DF[gram],
                "freq_noticias": fb,
                "docs_noticias": DFB[gram],
            }
        )
    out.sort(key=lambda r: -r["log_odds"])
    # Also: how often each BCB term appears in the corpus (prioritizes the useful official ones).
    bcb_path = SOURCES / "bcb.json"
    bcb_freq = []
    if bcb_path.exists():
        bcb = json.loads(bcb_path.read_text())
        glossary = Glossary([Term(r["termo"], "intermediario") for r in bcb])
        hits = collections.Counter()
        for text in official + news:
            hits.update(h.term.termo for h in glossary.match(text))
        bcb_freq = [{"termo": t, "freq": n} for t, n in hits.most_common()]
    SOURCES.mkdir(parents=True, exist_ok=True)
    (SOURCES / "corpus.json").write_text(
        json.dumps(
            {"candidatos": out[:limit], "bcb_no_corpus": bcb_freq}, ensure_ascii=False, indent=1
        )
    )
    print(
        f"corpus: {len(official)} docs oficiais, {len(news)} notícias → "
        f"{len(out)} candidatos (salvos {min(limit, len(out))}); "
        f"{len(bcb_freq)} termos BCB aparecem no corpus"
    )
    print("top 40:", ", ".join(r["termo"] for r in out[:40]))


# ------------------------------------------------------------------ propose: LLM


class Proposal(BaseModel):
    termo: str
    e_jargao_financeiro: bool
    nivel: Literal["basico", "intermediario", "avancado"]
    categoria: str
    definicao: str = Field(max_length=260)
    analogia: str = Field(max_length=260)
    variantes: list[str] = Field(max_length=4)


class ProposalBatch(BaseModel):
    termos: list[Proposal]


def _load_yaml(path: Path) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if path.exists() else []


def _dump_yaml(path: Path, rows: list[dict]) -> None:
    header = (
        "# Gerado por scripts/build_glossary.py. Revise: corrija nível/definição/analogia e\n"
        "# marque `revisado: true`; depois rode `promote`. Não apague linhas rejeitadas:\n"
        "# marque `rejeitado: true` (evita repropor).\n"
    )
    path.write_text(
        header + yaml.safe_dump(rows, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


_ACCENTED = re.compile(r"[À-ÿ]")


def _unaccented(row: dict) -> bool:
    text = f"{row.get('definicao', '')} {row.get('analogia', '')}"
    return bool(row.get("e_jargao")) and len(text) > 50 and not _ACCENTED.search(text)


async def propose(limit: int, batch_size: int, min_bcb_freq: int, redo_unaccented: bool) -> None:
    corpus = json.loads((SOURCES / "corpus.json").read_text())
    bcb = {r["termo"].lower(): r for r in json.loads((SOURCES / "bcb.json").read_text())}
    manual = _load_yaml(SOURCES / "manual.yaml")
    existing = _load_yaml(CANDIDATES)
    if redo_unaccented:
        dropped = [r["termo"] for r in existing if _unaccented(r) and not r.get("revisado")]
        existing = [r for r in existing if r["termo"] not in dropped]
        print(f"refazendo {len(dropped)} termos sem acentuação")
    done = {r["termo"].lower() for r in existing} | {r["termo"].lower() for r in _load_yaml(TERMS)}

    queue: list[tuple[str, str]] = []  # (termo, definição oficial ou "")
    manual_names = {m["termo"].lower() for m in manual}
    for m in manual:  # TAPI terms first
        if m["termo"].lower() not in done:
            official = bcb.get(m["termo"].lower(), {}).get("definicao", "")
            queue.append((m["termo"], official))
    for r in corpus["bcb_no_corpus"]:
        if r["freq"] >= min_bcb_freq and r["termo"].lower() not in done:
            queue.append((bcb[r["termo"].lower()]["termo"], bcb[r["termo"].lower()]["definicao"]))
    for r in corpus["candidatos"]:
        if r["termo"].lower() not in done and r["termo"].lower() not in bcb:
            queue.append((r["termo"], ""))
    queue = queue[:limit]
    print(f"{len(queue)} termos para propor (já existem {len(done)})")
    prompt = load_prompt("glossary_propose")

    async with Database(get_settings()) as db:
        router = LLMRouter(recorder=db_recorder(db))
        for i in range(0, len(queue), batch_size):
            chunk = queue[i : i + batch_size]
            listing = "\n".join(
                f"- {t}" + (f" | definição oficial: {d[:300]}" if d else "") for t, d in chunk
            )
            try:
                batch, info = await router.generate(
                    ProposalBatch,
                    [{"role": "user", "content": prompt.render(termos=listing)}],
                    purpose="glossary",
                    prompt_version=prompt.version,
                    max_tokens=6000,
                )
            except LLMError as exc:
                print(f"lote {i // batch_size + 1}: falhou ({exc}); rode de novo para continuar")
                break
            official = {t.lower(): d for t, d in chunk}
            for p in batch.termos:
                if p.termo.lower() not in official:
                    continue  # model renamed a term: drop instead of trusting it
                existing.append(
                    {
                        "termo": p.termo,
                        "nivel": p.nivel,
                        "variantes": p.variantes,
                        "categoria": p.categoria,
                        "definicao": p.definicao,
                        "analogia": p.analogia,
                        "fonte": (
                            "manual"
                            if p.termo.lower() in manual_names
                            else "bcb"
                            if official[p.termo.lower()]
                            else "corpus"
                        ),
                        "e_jargao": p.e_jargao_financeiro,
                        "revisado": False,
                    }
                )
            _dump_yaml(CANDIDATES, existing)  # save after every batch: resumable
            print(
                f"lote {i // batch_size + 1}: {len(batch.termos)} termos via "
                f"{info.provider}/{info.key_label} ({info.latency_ms} ms)"
            )


# ------------------------------------------------------------------ promote / stats


def promote() -> None:
    candidates = _load_yaml(CANDIDATES)
    terms = _load_yaml(TERMS)
    known = {t["termo"].lower() for t in terms}
    moved = [
        c
        for c in candidates
        if c.get("revisado")
        and not c.get("rejeitado")
        and c.get("e_jargao", True)
        and c["termo"].lower() not in known
    ]
    keep = [c for c in candidates if c not in moved]
    for c in moved:
        c.pop("e_jargao", None)
    TERMS.write_text(
        "# Glossário revisado (fonte de verdade). Gerado por `promote`.\n"
        + yaml.safe_dump(terms + moved, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    _dump_yaml(CANDIDATES, keep)
    print(f"promovidos {len(moved)} termos → {TERMS} (total {len(terms) + len(moved)})")


def stats() -> None:
    for path in (TERMS, CANDIDATES):
        rows = _load_yaml(path)
        jargon = [r for r in rows if r.get("e_jargao", True) and not r.get("rejeitado")]
        levels = collections.Counter(r.get("nivel") for r in jargon)
        print(f"{path.name}: {len(rows)} linhas, {len(jargon)} jargão → {dict(levels)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-bcb")
    m = sub.add_parser("mine")
    m.add_argument("--limit", type=int, default=600)
    p = sub.add_parser("propose")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--batch", type=int, default=20)
    p.add_argument("--min-bcb-freq", type=int, default=3)
    p.add_argument(
        "--redo-unaccented",
        action="store_true",
        help="repropõe termos cuja definição veio sem acentuação",
    )
    sub.add_parser("promote")
    sub.add_parser("stats")
    args = parser.parse_args()
    if args.cmd == "seed-bcb":
        asyncio.run(seed_bcb())
    elif args.cmd == "mine":
        asyncio.run(mine(args.limit))
    elif args.cmd == "propose":
        asyncio.run(propose(args.limit, args.batch, args.min_bcb_freq, args.redo_unaccented))
    elif args.cmd == "promote":
        promote()
    else:
        stats()


if __name__ == "__main__":
    main()

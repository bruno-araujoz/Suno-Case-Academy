"""Find glossary terms in a text — locally, in milliseconds.

- Terms live in glossary/terms.yaml (reviewed) and glossary/candidates.yaml (not yet reviewed;
  used only when `include_unreviewed=True`, the MVP default until the team reviews them).
- Matching is accent/case-insensitive on a length-preserving folded copy of the text, so match
  offsets map back to the original. Acronyms (CDI, IPCA, PIB...) are matched case-sensitively.
- Longest match wins: "juros futuros" is one hit, not "juros" + "futuros".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_DIR = ROOT / "glossary"
Level = Literal["basico", "intermediario", "avancado"]
LEVEL_RANK = {"basico": 0, "intermediario": 1, "avancado": 2}
_ACRONYM = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,7}$")


def fold_keep_length(text: str) -> str:
    """Lowercase + strip accents, one output char per input char (offsets stay valid)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)
        stripped = "".join(c for c in base if not unicodedata.combining(c))
        out.append((stripped[:1] or ch).lower())
    return "".join(out)


@dataclass(frozen=True)
class Term:
    termo: str
    nivel: Level
    variantes: tuple[str, ...] = ()
    categoria: str = ""
    definicao: str = ""
    analogia: str = ""
    fonte: str = ""
    revisado: bool = False

    @property
    def forms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.termo, *self.variantes)))


@dataclass(frozen=True)
class TermHit:
    term: Term
    start: int
    end: int
    surface: str


@dataclass
class Glossary:
    terms: list[Term]
    _patterns: list[tuple[re.Pattern[str], bool, Term]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        compiled = []
        for term in self.terms:
            for form in term.forms:
                form = form.strip()
                if not form:
                    continue
                acronym = bool(_ACRONYM.match(form))
                body = re.escape(form if acronym else fold_keep_length(form))
                body = body.replace(r"\ ", r"\s+")  # tolerate line breaks / double spaces
                compiled.append((re.compile(rf"(?<![\w-]){body}(?![\w-])"), acronym, term))
        # longer forms first: a cheap pre-order for the longest-match resolution below
        compiled.sort(key=lambda c: -len(c[0].pattern))
        self._patterns = compiled

    def match(self, text: str) -> list[TermHit]:
        folded = fold_keep_length(text)
        candidates: list[TermHit] = []
        for pattern, acronym, term in self._patterns:
            haystack = text if acronym else folded
            for m in pattern.finditer(haystack):
                candidates.append(TermHit(term, m.start(), m.end(), text[m.start() : m.end()]))
        # longest match wins; ties keep the first (longer pattern compiled earlier)
        candidates.sort(key=lambda h: (h.start, -(h.end - h.start)))
        hits: list[TermHit] = []
        last_end = -1
        for hit in candidates:
            if hit.start >= last_end:
                hits.append(hit)
                last_end = hit.end
        return hits

    def by_name(self) -> dict[str, Term]:
        return {t.termo: t for t in self.terms}


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return data if isinstance(data, list) else data.get("termos", [])


def _to_term(raw: dict) -> Term:
    return Term(
        termo=str(raw["termo"]).strip(),
        nivel=raw.get("nivel", "intermediario"),
        variantes=tuple(str(v) for v in raw.get("variantes") or ()),
        categoria=raw.get("categoria") or "",
        definicao=raw.get("definicao") or "",
        analogia=raw.get("analogia") or "",
        fonte=raw.get("fonte") or "",
        revisado=bool(raw.get("revisado")),
    )


@lru_cache(maxsize=4)
def load_glossary(include_unreviewed: bool = True, directory: Path = GLOSSARY_DIR) -> Glossary:
    """Reviewed terms always; unreviewed candidates only if asked.

    Precedence on conflicts: reviewed > manual seed > others. A term whose name is a variant of
    a higher-precedence term is dropped (e.g. BCB's "TIR" = transfer system loses to the manual
    "Taxa Interna de Retorno", variant "TIR" — the meaning used in financial news).
    """
    raw = [(_to_term(r), r) for r in _read(directory / "terms.yaml")]
    if include_unreviewed:
        raw += [
            (_to_term(r), r)
            for r in _read(directory / "candidates.yaml")
            if r.get("e_jargao", True) and not r.get("rejeitado")
        ]

    def rank(item: tuple[Term, dict]) -> int:
        term, _ = item
        return 0 if term.revisado else 1 if term.fonte == "manual" else 2

    terms: dict[str, Term] = {}
    claimed: set[str] = set()  # every surface form already owned by a stronger term
    for term, _ in sorted(raw, key=rank):
        key = term.termo.lower()
        if key in terms or key in claimed or term.nivel not in LEVEL_RANK:
            continue
        terms[key] = term
        claimed.update(f.lower() for f in term.forms)
    return Glossary(list(terms.values()))

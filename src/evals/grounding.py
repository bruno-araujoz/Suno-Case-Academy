"""Factual grounding against the anchors (the facts verified against the source documents).

- Every figure in the output must exist in the anchors → an invented number is a HARD failure.
- Anchor coverage: share of *central* facts present in the output (by one of their figures, or by
  ≥ 50% of their content tokens) — this is what blocks "summarizing by shortening".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from generation.schemas import Anchors
from scraper.relevance.text import numbers, tokens


@dataclass
class GroundingReport:
    ungrounded_numbers: list[str] = field(default_factory=list)
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = len(self.covered) + len(self.missing)
        return round(len(self.covered) / total, 3) if total else 1.0


def anchor_numbers(anchors: Anchors) -> set[str]:
    found: set[str] = set()
    for fact in anchors.fatos:
        found |= numbers(" ".join([fact.afirmacao, fact.citacao, *fact.numeros]))
    found |= numbers(" ".join([anchors.evento, anchors.contexto, *anchors.implicacoes]))
    return found


def ground(output_text: str, anchors: Anchors) -> GroundingReport:
    report = GroundingReport()
    allowed = anchor_numbers(anchors)
    report.ungrounded_numbers = sorted(numbers(output_text) - allowed)
    out_numbers = numbers(output_text)
    out_tokens = tokens(output_text)
    central = [f for f in anchors.fatos if f.central] or anchors.fatos
    for fact in central:
        fact_numbers = numbers(" ".join(fact.numeros)) or numbers(fact.afirmacao)
        fact_tokens = {t for t in tokens(fact.afirmacao) if not t.startswith("#")}
        by_number = bool(fact_numbers & out_numbers)
        by_words = bool(fact_tokens) and len(fact_tokens & out_tokens) / len(fact_tokens) >= 0.5
        (report.covered if by_number or by_words else report.missing).append(fact.id)
    return report

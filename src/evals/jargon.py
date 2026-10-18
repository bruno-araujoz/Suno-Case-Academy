"""Jargon metrics: density per glossary layer and terms used without explanation.

A term counts as *explained* when, right after it, the text opens an apposition — "(", "—", "–",
":" or ", que é/são" — or when an explanation marker ("ou seja", "isto é", "que significa",
"funciona como", "é como"...) appears after the term in the same sentence or at the start of the
next one. Analogies are counted by their own markers ("é como", "como se", "imagine"...).
Deterministic on purpose: the same text always gets the same score.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from glossary.matcher import Glossary, TermHit

from .readability import _WORD, sentences

_APPOSITION = re.compile(r"^\s*(\(|—|–|:|,\s*(que|o que|ou seja)\s+(é|são|significa|quer dizer))")
# Matched on the lowercased ORIGINAL text: accents matter ("é como" explains, "e como" does not).
_EXPLAIN = re.compile(
    r"\b(ou seja|isto é|isso é|que significa|o que significa|quer dizer|significa que|"
    r"funciona como|é como|é quando|nada mais é|trata-se de|que é o|que é a|que são|"
    r"chamad[oa]s? de|conhecid[oa]s? como|ou melhor)\b"
)
_ANALOGY = re.compile(
    r"(é como se|como se fosse|\bé como\b|funciona como|\bimagine\b|\bpense em\b|"
    r"parecido com|equivale a|assim como|da mesma forma que)"
)


@dataclass
class JargonReport:
    words: int
    counts: Counter = field(default_factory=Counter)  # hits per nivel
    unexplained: dict[str, list[str]] = field(default_factory=dict)  # nivel → terms
    analogies: int = 0
    hits: list[TermHit] = field(default_factory=list)

    def density(self, nivel: str) -> float:
        return round(100 * self.counts.get(nivel, 0) / self.words, 2) if self.words else 0.0


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, cursor = [], 0
    for sent in sentences(text):
        start = text.find(sent, cursor)
        if start < 0:
            continue
        spans.append((start, start + len(sent)))
        cursor = start + len(sent)
    return spans or [(0, len(text))]


def is_explained(text: str, lower: str, hit: TermHit, spans: list[tuple[int, int]]) -> bool:
    if _APPOSITION.match(text[hit.end : hit.end + 40]):
        return True
    idx = next((i for i, (s, e) in enumerate(spans) if s <= hit.start < e), None)
    if idx is None:
        return False
    after_in_sentence = lower[hit.end : spans[idx][1]]
    if _EXPLAIN.search(after_in_sentence):
        return True
    if idx + 1 < len(spans):
        next_start = lower[spans[idx + 1][0] : spans[idx + 1][0] + 80]
        return bool(_EXPLAIN.search(next_start))
    return False


def analyze(text: str, glossary: Glossary) -> JargonReport:
    # char-wise lower keeps offsets valid even for chars whose lowercase is 2 chars (e.g. "İ")
    lower = "".join(c.lower() if len(c.lower()) == 1 else c for c in text)
    spans = _sentence_spans(text)
    report = JargonReport(words=len(_WORD.findall(text)))
    seen_explained: set[str] = set()
    first_hit: dict[str, TermHit] = {}
    for hit in glossary.match(text):
        report.hits.append(hit)
        report.counts[hit.term.nivel] += 1
        key = hit.term.termo
        first_hit.setdefault(key, hit)
        if is_explained(text, lower, hit, spans):
            seen_explained.add(key)
    # A term is fine if it is explained at least once (usually at first use).
    for key, hit in first_hit.items():
        if key not in seen_explained:
            report.unexplained.setdefault(hit.term.nivel, []).append(key)
    report.analogies = len(_ANALOGY.findall(lower))
    return report

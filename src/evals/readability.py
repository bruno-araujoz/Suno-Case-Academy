"""Flesch Reading Ease adapted to Brazilian Portuguese (Martins et al., 1996).

    FRE_pt = 248.835 − 1.015 · (words / sentences) − 84.6 · (syllables / words)

Syllables via pyphen's pt_BR hyphenation dictionary (Portuguese hyphenation follows syllable
boundaries). Own implementation on purpose: `textstat` (pt) gave −25.5 on a text where this
formula gives 15.7 (measured 2026-10-14).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

_WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)*")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n{2,}|\n(?=[-•*–]\s)")
MIN_WORDS = 30  # below this the formula is too noisy to be meaningful


@lru_cache(maxsize=1)
def _dic():
    import pyphen

    return pyphen.Pyphen(lang="pt_BR")


@lru_cache(maxsize=50_000)
def syllables(word: str) -> int:
    return max(1, sum(len(_dic().inserted(part).split("-")) for part in word.lower().split("-")))


@dataclass(frozen=True)
class Readability:
    flesch: float | None
    words: int
    sentences: int
    words_per_sentence: float
    syllables_per_word: float


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if _WORD.search(s or "")]


def readability(text: str) -> Readability:
    sents = sentences(text)
    words = _WORD.findall(text)
    if not words or not sents:
        return Readability(None, len(words), len(sents), 0.0, 0.0)
    wps = len(words) / len(sents)
    spw = sum(syllables(w) for w in words) / len(words)
    score = 248.835 - 1.015 * wps - 84.6 * spw if len(words) >= MIN_WORDS else None
    return Readability(
        round(score, 1) if score is not None else None,
        len(words),
        len(sents),
        round(wps, 1),
        round(spw, 2),
    )

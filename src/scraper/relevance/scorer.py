"""Deterministic relevance: lexical event signal + source tier + cross-coverage + recency."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import yaml

from ..core.config import Settings
from .text import fold

GLOSSARY = Path(__file__).resolve().parents[3] / "glossary" / "events.yaml"
TIER_SCORE = {"official": 1.0, "news": 0.6, "coverage": 0.0}
LEXICAL_SATURATION = 2.5  # sum of weights that maps to ~0.63 (1 - e^-1)


@lru_cache(maxsize=1)
def load_terms(path: Path = GLOSSARY) -> list[tuple[re.Pattern[str], float]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    terms = {term: float(w) for group in data.values() for term, w in group.items()}
    return [
        (re.compile(rf"(?<![a-z0-9]){re.escape(fold(t))}(?![a-z0-9])"), w) for t, w in terms.items()
    ]


def lexical_score(title: str, body: str | None) -> float:
    """Distinct glossary terms; title hits count double. Saturating map to [0, 1)."""
    title_f, body_f = fold(title), fold((body or "")[:2000])
    total = 0.0
    for pattern, weight in load_terms():
        if pattern.search(title_f):
            total += 2 * weight
        elif pattern.search(body_f):
            total += weight
    return round(1 - math.exp(-total / LEXICAL_SATURATION), 4)


def coverage_score(publishers: int) -> float:
    """1 publisher → 0; 5+ distinct publishers → 1."""
    return round(min(1.0, max(0, publishers - 1) / 4), 4)


def recency_score(
    published_at: datetime, half_life_hours: float, now: datetime | None = None
) -> float:
    age_h = max(0.0, ((now or datetime.now(UTC)) - published_at).total_seconds() / 3600)
    return round(math.exp(-math.log(2) * age_h / half_life_hours), 4)


@dataclass
class Breakdown:
    lexical: float
    tier: float
    coverage: float
    recency: float
    score: float


def score(
    settings: Settings,
    *,
    lexical: float,
    tier: str,
    publishers: int,
    published_at: datetime,
    now: datetime | None = None,
) -> Breakdown:
    w_lex, w_tier, w_cov, w_rec = settings.relevance_weights
    parts = (
        lexical,
        TIER_SCORE.get(tier, 0.0),
        coverage_score(publishers),
        recency_score(published_at, settings.relevance_half_life_hours, now),
    )
    total = w_lex * parts[0] + w_tier * parts[1] + w_cov * parts[2] + w_rec * parts[3]
    return Breakdown(*parts, score=round(total, 4))

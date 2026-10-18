"""Level classifiers for the confusion matrix (TAPI deliverable 6).

Two views, on purpose:
- `spec_level`: the rules in config/levels.yaml. Says whether outputs MEET each level's spec —
  but it is the same yardstick that guided generation, so a perfect diagonal is partly circular.
- `CentroidClassifier`: nearest centroid in a standardized feature space, with centroids taken
  from EXTERNAL references — official documents (≈ avançado), portal news (≈ intermediário) and
  the team-labeled set for iniciante (provisional Martins-scale prior while it does not exist).
  This is the independent evidence that the levels really differ.
"""

from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from glossary.matcher import Glossary

from .evaluator import targets_for
from .jargon import analyze
from .readability import readability

FEATURES = ("flesch", "densidade_tecnica", "analogias_100", "nao_explicados_pct")
LEVELS = ("iniciante", "intermediario", "avancado")
LABELED_DIR = Path(__file__).resolve().parents[2] / "evals" / "labeled"
# Provisional beginner reference until the team-labeled set exists (Martins: 50–75 = "fácil").
BEGINNER_PRIOR = {
    "flesch": 65.0,
    "densidade_tecnica": 1.0,
    "analogias_100": 1.5,
    "nao_explicados_pct": 0.0,
}


def features(text: str, glossary: Glossary) -> dict[str, float] | None:
    read = readability(text)
    if read.flesch is None:
        return None
    jar = analyze(text, glossary)
    terms = len({h.term.termo for h in jar.hits if h.term.nivel != "basico"})
    unexplained = sum(len(v) for k, v in jar.unexplained.items() if k != "basico")
    return {
        "flesch": read.flesch,
        "densidade_tecnica": jar.density("avancado") + jar.density("intermediario"),
        "analogias_100": 100 * jar.analogies / jar.words if jar.words else 0.0,
        "nao_explicados_pct": unexplained / terms if terms else 0.0,
    }


def spec_level(metrics: dict, fmt: str, cfg: dict) -> str:
    """Which level's spec does this output satisfy? (strictest first)."""
    flesch = metrics.get("flesch") or 0
    unexplained = metrics.get("nao_explicados") or {}
    beginner = targets_for("iniciante", fmt, cfg)
    advanced = targets_for("avancado", fmt, cfg)
    if (
        not unexplained.get("intermediario")
        and not unexplained.get("avancado")
        and metrics.get("analogias", 0) >= beginner.get("analogies_min", 1)
        and flesch >= beginner.get("flesch_min", 0)
    ):
        return "iniciante"
    if (
        metrics.get("densidade_tecnica", 0) >= advanced.get("technical_density_min", 0)
        and flesch <= advanced.get("flesch_max", 100)
        and metrics.get("analogias", 0) <= advanced.get("analogies_max", 99)
    ):
        return "avancado"
    return "intermediario"


@dataclass
class CentroidClassifier:
    centroids: dict[str, dict[str, float]]
    scale: dict[str, float]
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def fit(cls, refs: dict[str, list[dict[str, float]]], sources: dict[str, str]):
        centroids = {
            lvl: {f: st.median(r[f] for r in rows) for f in FEATURES}
            for lvl, rows in refs.items()
            if rows
        }
        pooled = [r for rows in refs.values() for r in rows]
        scale = {f: (st.pstdev([r[f] for r in pooled]) or 1.0) for f in FEATURES}
        return cls(centroids, scale, sources)

    def predict(self, feats: dict[str, float]) -> str:
        def dist(c: dict[str, float]) -> float:
            return math.sqrt(sum(((feats[f] - c[f]) / self.scale[f]) ** 2 for f in FEATURES))

        return min(self.centroids, key=lambda lvl: dist(self.centroids[lvl]))


def labeled_texts() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {lvl: [] for lvl in LEVELS}
    for path in sorted(LABELED_DIR.glob("*.yaml")):
        for row in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            if row.get("texto") and row.get("nivel") in out and not row.get("exemplo"):
                out[row["nivel"]].append(row["texto"])
    return out


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    matrix = {t: {p: 0 for p in LEVELS} for t in LEVELS}
    for true, pred in pairs:
        matrix[true][pred] += 1
    return matrix


def accuracy(pairs: list[tuple[str, str]]) -> float:
    return round(sum(t == p for t, p in pairs) / len(pairs), 3) if pairs else 0.0

"""Group documents/headlines about the same event.

Items are assigned (in chronological order) to the existing cluster with the most similar
*member* — Jaccard over title tokens incl. figures and tickers — or start a new cluster. Items
are never used to merge two clusters, which prevents the chaining that single-link produces
(A~B~C... turning all "Ibovespa"/"juros" news into one blob).

Tuned on a live sample (2026-10-09, 336 docs + 550 Google News headlines): Jaccard >= 0.35
(or >= 0.15 with a shared ticker) kept the IPCA 0,82% release in one 40-outlet cluster and the
Ibovespa record in a separate 24-outlet one, with no mixed clusters among the top ones.
(v1 used MinHash LSH + union-find: it chained into a 110-outlet cluster and pulled in scipy.)
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .text import tickers, tokens

MAX_POSTINGS = 400  # tokens shared by more clusters than this are too generic to propose matches


@dataclass
class Item:
    key: str
    title: str
    publisher: str
    published_at: datetime
    lead: str = ""
    tickers: set[str] = field(default_factory=set)


@dataclass
class _Cluster:
    id: str
    started: datetime
    members: list[tuple[str, frozenset[str]]] = field(default_factory=list)
    tickers: set[str] = field(default_factory=set)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class Clusterer:
    def __init__(
        self,
        threshold: float = 0.35,
        ticker_threshold: float = 0.15,
        max_gap: timedelta = timedelta(hours=72),
    ) -> None:
        self.threshold = threshold
        self.ticker_threshold = ticker_threshold
        self.max_gap = max_gap
        self.items: dict[str, Item] = {}
        self._clusters: list[_Cluster] = []
        self._of: dict[str, int] = {}
        self._index: defaultdict[str, set[int]] = defaultdict(set)

    def add(self, item: Item) -> str:
        if item.key in self.items:
            return self.cluster_of(item.key)
        item.tickers = item.tickers or tickers(item.title)
        toks = frozenset(tokens(item.title))
        candidates: set[int] = set()
        for tok in toks:
            postings = self._index[tok]
            if len(postings) <= MAX_POSTINGS:
                candidates |= postings

        best, best_sim = None, 0.0
        for ci in candidates:
            cluster = self._clusters[ci]
            if abs(item.published_at - cluster.started) > self.max_gap:
                continue
            sim = max(jaccard(toks, member) for _, member in cluster.members)
            shared_ticker = bool(item.tickers & cluster.tickers)
            if (
                sim >= self.threshold or (shared_ticker and sim >= self.ticker_threshold)
            ) and sim > best_sim:
                best, best_sim = ci, sim

        if best is None:
            self._clusters.append(_Cluster(id=item.key, started=item.published_at))
            best = len(self._clusters) - 1
        cluster = self._clusters[best]
        cluster.members.append((item.key, toks))
        cluster.tickers |= item.tickers
        self.items[item.key] = item
        self._of[item.key] = best
        for tok in toks:
            self._index[tok].add(best)
        return cluster.id

    def cluster_of(self, key: str) -> str:
        return self._clusters[self._of[key]].id

    def clusters(self) -> dict[str, list[Item]]:
        return {c.id: [self.items[k] for k, _ in c.members] for c in self._clusters}

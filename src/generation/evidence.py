"""Pick and compress an event's documents into the evidence sent to the anchor LLM call.

Budgeted (~12k tokens by default) so it fits the free tiers. Sentences are kept in their original
order; when a document is too long, the ones with figures, glossary terms and the lead win.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass

from evals.readability import sentences
from glossary.matcher import Glossary
from scraper.core.models import Document
from scraper.relevance.text import numbers

CHARS_PER_TOKEN = 4


@dataclass
class EvidenceDoc:
    id: str
    source: str
    tier: str
    doc_type: str
    title: str
    url: str
    published_at: str
    text: str  # compressed text actually sent to the LLM
    full_text: str  # original, used to verify citations/figures

    def public(self) -> dict:
        data = asdict(self)
        data.pop("full_text")
        return data


def _compress(text: str, budget_chars: int, glossary: Glossary) -> str:
    if len(text) <= budget_chars:
        return text
    sents = sentences(text)
    scored = []
    for i, sent in enumerate(sents):
        score = 2.0 * bool(numbers(sent)) + 1.0 * len(glossary.match(sent)) + (3.0 if i < 3 else 0)
        scored.append((score, i, sent))
    keep, used = set(), 0
    for _, i, sent in sorted(scored, key=lambda x: (-x[0], x[1])):
        if used + len(sent) > budget_chars:
            continue
        keep.add(i)
        used += len(sent) + 1
    return " ".join(sents[i] for i in sorted(keep))


def build_evidence(
    docs: list[Document], glossary: Glossary, budget_tokens: int = 12_000
) -> list[EvidenceDoc]:
    usable = [d for d in docs if d.content_text and len(d.content_text) > 200]
    if not usable:
        return []
    budget = budget_tokens * CHARS_PER_TOKEN
    weights = [2.0 if d.tier == "official" else 1.0 for d in usable]
    out = []
    for n, (doc, weight) in enumerate(zip(usable, weights, strict=True), start=1):
        share = int(budget * weight / sum(weights))
        out.append(
            EvidenceDoc(
                id=f"D{n}",
                source=doc.source,
                tier=doc.tier,
                doc_type=doc.doc_type,
                title=doc.title,
                url=doc.url,
                published_at=doc.published_at.isoformat(),
                text=_compress(doc.content_text or "", share, glossary),
                full_text=doc.content_text or "",
            )
        )
    return out


def evidence_prompt(evidence: list[EvidenceDoc]) -> str:
    return "\n\n".join(
        f"[{e.id}] {e.title}\nFonte: {e.source} ({e.tier}, {e.doc_type}) · {e.published_at[:10]}\n"
        f"{e.text}"
        for e in evidence
    )


def docs_hash(evidence: list[EvidenceDoc]) -> str:
    h = hashlib.sha256()
    for e in evidence:
        h.update(e.url.encode())
        h.update(hashlib.sha256(e.full_text.encode()).digest())
    return h.hexdigest()[:16]

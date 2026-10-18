"""Anchor extraction (LLM) + deterministic verification against the source documents.

The LLM proposes facts with literal citations and figures; code keeps only those whose citation
really exists in the cited document (fuzzy ≥ 90 on accent-folded text) and whose figures appear
in it. This makes the anchors a *verified* ground truth for the writer and the evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from glossary.matcher import fold_keep_length
from llm.prompts import load_prompt
from llm.router import CallInfo, LLMRouter
from scraper.relevance.text import numbers

from .evidence import EvidenceDoc, evidence_prompt
from .schemas import Anchors

CITATION_MIN_SCORE = 90


@dataclass
class AnchorResult:
    anchors: Anchors
    dropped: list[dict] = field(default_factory=list)
    call: CallInfo | None = None


def verify(anchors: Anchors, evidence: list[EvidenceDoc]) -> tuple[Anchors, list[dict]]:
    docs = {e.id: e for e in evidence}
    kept, dropped = [], []
    for fact in anchors.fatos:
        doc = docs.get(fact.doc_id)
        if doc is None:
            dropped.append({"id": fact.id, "motivo": f"doc_id inexistente: {fact.doc_id}"})
            continue
        source = fold_keep_length(doc.full_text)
        citation = fold_keep_length(fact.citacao)
        score = fuzz.partial_ratio(citation, source) if citation.strip() else 0
        if score < CITATION_MIN_SCORE:
            dropped.append(
                {"id": fact.id, "motivo": f"citação não encontrada (similaridade {score:.0f})"}
            )
            continue
        missing = numbers(" ".join(fact.numeros)) - numbers(doc.full_text)
        if missing:
            dropped.append(
                {
                    "id": fact.id,
                    "motivo": "números ausentes da fonte: " + ", ".join(sorted(missing)),
                }
            )
            continue
        kept.append(fact)
    if kept and not any(f.central for f in kept):
        kept[0] = kept[0].model_copy(update={"central": True})
    return anchors.model_copy(update={"fatos": kept}), dropped


async def extract_anchors(router: LLMRouter, evidence: list[EvidenceDoc]) -> AnchorResult:
    prompt = load_prompt("anchor")
    raw, call = await router.generate(
        Anchors,
        [{"role": "user", "content": prompt.render(documentos=evidence_prompt(evidence))}],
        purpose="anchor",
        prompt_version=prompt.version,
        temperature=0.1,
        max_tokens=4000,
    )
    anchors, dropped = verify(raw, evidence)
    if len(anchors.fatos) < 2:
        raise ValueError(
            f"âncoras insuficientes após verificação ({len(anchors.fatos)} fatos; "
            f"descartados: {dropped})"
        )
    return AnchorResult(anchors, dropped, call)

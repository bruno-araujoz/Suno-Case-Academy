"""Level brief (deterministic): which terms to explain, which are free, the level's targets.

This is the "audience adapter" of the TAPI without an LLM call: the glossary decides, per level,
which of the event's terms the reader needs explained — and hands the writer the definition and
analogy to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from glossary.matcher import LEVEL_RANK, Glossary, Term

from .schemas import Anchors, Level

MAX_SUGGESTIONS = 12

# Highest glossary layer a reader of each level understands WITHOUT explanation.
UNDERSTANDS = {"iniciante": "basico", "intermediario": "intermediario", "avancado": "avancado"}

AUDIENCE = {
    "iniciante": "Investidor INICIANTE: zero jargão financeiro desacompanhado de analogia "
    "cotidiana; foco no impacto prático no bolso. Frases curtas e diretas.",
    "intermediario": "Investidor INTERMEDIÁRIO: vocabulário de mercado padrão (CDI, Selic, IPCA, "
    "dividendos) sem explicação; foco em alocação e tendências.",
    "avancado": "Público AVANÇADO/INSTITUCIONAL: jargão técnico pleno preservado (curva de juros, "
    "forward guidance, hiato do produto, EBITDA ajustado, covenants); foco analítico e "
    "metodológico. Não simplifique nem use analogias didáticas.",
}


@dataclass
class Brief:
    level: Level
    explain: list[Term] = field(default_factory=list)
    free: list[Term] = field(default_factory=list)
    suggest: list[Term] = field(default_factory=list)  # advanced vocabulary for the event's topic

    def explain_text(self) -> str:
        if not self.explain:
            return "(nenhum)"
        return "\n".join(
            f"- {t.termo}: {t.definicao}"
            + (f" Analogia possível: {t.analogia}" if t.analogia else "")
            for t in self.explain
        )

    def free_text(self) -> str:
        return ", ".join(t.termo for t in self.free) or "(nenhum)"

    def suggest_text(self) -> str:
        if not self.suggest:
            return "(não se aplica)"
        return (
            ", ".join(t.termo for t in self.suggest)
            + "\n(use para DESCREVER os fatos com precisão técnica; não acrescente fatos novos)"
        )


def anchors_text(anchors: Anchors) -> str:
    lines = [f"Evento: {anchors.evento}", f"Contexto: {anchors.contexto}"]
    for f in anchors.fatos:
        nums = f" | números: {', '.join(f.numeros)}" if f.numeros else ""
        lines.append(f"{f.id}{' [CENTRAL]' if f.central else ''}: {f.afirmacao}{nums}")
    lines += [f"Implicação: {i}" for i in anchors.implicacoes]
    return "\n".join(lines)


def build_brief(level: Level, anchors: Anchors, glossary: Glossary, suggest: bool = True) -> Brief:
    limit = LEVEL_RANK[UNDERSTANDS[level]]
    seen: dict[str, Term] = {}
    for hit in glossary.match(anchors_text(anchors)):
        seen.setdefault(hit.term.termo, hit.term)
    brief = Brief(level=level)
    for term in seen.values():
        (brief.free if LEVEL_RANK[term.nivel] <= limit else brief.explain).append(term)
    if level == "avancado" and suggest:
        # The anchors alone rarely carry enough jargon for the institutional register: suggest
        # advanced glossary terms from the same categories as the event's own terms.
        categories = {t.categoria for t in seen.values() if t.categoria}
        brief.suggest = [
            t
            for t in glossary.terms
            if t.nivel == "avancado" and t.categoria in categories and t.termo not in seen
        ][:MAX_SUGGESTIONS]
    return brief


def targets_text(level: Level, cfg: dict, fmt: str | None = None) -> str:
    from evals.evaluator import targets_for

    t = targets_for(level, fmt, cfg) if fmt else cfg[level]
    lines = []
    if "flesch_min" in t:
        lines.append(
            f"- Legibilidade Flesch-PT ≥ {t['flesch_min']} (frases curtas, palavras simples)"
        )
    if "flesch_max" in t:
        lines.append(f"- Legibilidade Flesch-PT ≤ {t['flesch_max']} (linguagem técnica plena)")
    if t.get("unexplained_max"):
        lines.append("- Nenhum termo da lista 'DEVE EXPLICAR' sem explicação")
    if "analogies_min" in t:
        lines.append(f"- Pelo menos {t['analogies_min']} analogia do cotidiano ('é como...')")
    if "analogies_max" in t:
        lines.append(f"- No máximo {t['analogies_max']} analogia (público técnico)")
    if "technical_density_min" in t:
        lines.append(
            f"- Pelo menos {t['technical_density_min']} termos técnicos de mercado a "
            "cada 100 palavras"
        )
    lines.append(f"- Cobrir ≥ {int(t['anchor_coverage_min'] * 100)}% dos fatos [CENTRAL]")
    return "\n".join(lines)

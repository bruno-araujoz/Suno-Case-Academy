"""Run all deterministic checks for one generation and produce an actionable report."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from generation.schemas import Anchors, Carousel, Format, Level, Script, reader_text
from glossary.matcher import Glossary

from .grounding import ground
from .jargon import analyze
from .readability import readability

LEVELS_FILE = Path(__file__).resolve().parents[2] / "config" / "levels.yaml"


@lru_cache(maxsize=1)
def level_targets(path: Path = LEVELS_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def targets_for(level: str, fmt: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Level targets with the format's overrides applied (scripts/slides read differently)."""
    cfg = cfg or level_targets()
    override = (cfg.get("format_overrides") or {}).get(fmt, {}).get(level, {})
    return {**cfg[level], **override}


@dataclass
class Check:
    name: str
    value: Any
    target: str
    passed: bool
    hard: bool = False  # hard failures (invented numbers) make the attempt unusable
    feedback: str = ""


@dataclass
class EvalReport:
    fmt: str
    level: str
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def score(self) -> float:
        """Share of checks passed; 0 if any hard check failed (used to pick the best attempt)."""
        if any(c.hard and not c.passed for c in self.checks):
            return 0.0
        return round(sum(c.passed for c in self.checks) / len(self.checks), 3) if self.checks else 0

    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def feedback(self) -> str:
        """Numeric, actionable failure report injected into the rewrite prompt."""
        return "\n".join(
            f"- {c.name}: obtido {c.value}, alvo {c.target}. {c.feedback}".strip()
            for c in self.failures()
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "fmt": self.fmt,
            "level": self.level,
            "passed": self.passed,
            "score": self.score,
            "metrics": self.metrics,
            "checks": [asdict(c) for c in self.checks],
        }


def _format_checks(fmt: Format, content: BaseModel, cfg: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    if fmt == "carrossel":
        assert isinstance(content, Carousel)
        roles = [s.papel for s in content.slides]
        ok = roles[0] == "gancho" and roles[-1] == "conclusao"
        checks.append(
            Check(
                "estrutura do carrossel",
                " → ".join(roles),
                "gancho … conclusão",
                ok,
                feedback="Comece com um slide 'gancho' e termine com 'conclusao'.",
            )
        )
    elif fmt == "roteiro":
        assert isinstance(content, Script)
        lim = cfg["formats"]["roteiro"]
        spoken = sum(len(b.fala.split()) for b in content.blocos)
        checks.append(
            Check(
                "palavras faladas",
                spoken,
                f"≤ {lim['max_spoken_words']}",
                spoken <= lim["max_spoken_words"],
                feedback="Corte a fala: 60 s comportam ~150 palavras.",
            )
        )
        times = [(b.inicio_s, b.fim_s) for b in content.blocos]
        ordered = all(a < b for a, b in times) and all(
            times[i][1] <= times[i + 1][0] for i in range(len(times) - 1)
        )
        end = max(b for _, b in times)
        checks.append(
            Check(
                "linha do tempo",
                f"{times[0][0]}–{end}s",
                f"crescente, ≤ {lim['max_seconds']}s",
                ordered and end <= lim["max_seconds"],
                feedback="Marcações de tempo crescentes, sem sobreposição, até 60 s.",
            )
        )
    return checks


def add_judge_check(report: EvalReport, result) -> None:
    """Attach the (optional) LLM judge verdicts as one more check."""
    bad = result.unsupported
    report.metrics["afirmacoes_nao_apoiadas"] = [c.afirmacao for c in bad]
    report.checks.append(
        Check(
            "afirmações sem número não apoiadas (juiz)",
            len(bad),
            "0",
            not bad,
            feedback=(
                "Remova ou reescreva com base nos fatos: "
                + "; ".join(f"'{c.afirmacao[:80]}' ({c.motivo})" for c in bad)
            )
            if bad
            else "",
        )
    )


def evaluate(
    fmt: Format,
    level: Level,
    content: BaseModel,
    anchors: Anchors,
    glossary: Glossary,
    cfg: dict[str, Any] | None = None,
) -> EvalReport:
    cfg = cfg or level_targets()
    target = targets_for(level, fmt, cfg)
    text = reader_text(fmt, content)
    report = EvalReport(fmt=fmt, level=level)

    read = readability(text)
    jar = analyze(text, glossary)
    grd = ground(text, anchors)
    report.metrics = {
        "flesch": read.flesch,
        "palavras": read.words,
        "palavras_por_frase": read.words_per_sentence,
        "silabas_por_palavra": read.syllables_per_word,
        "termos": dict(jar.counts),
        "densidade_avancado": jar.density("avancado"),
        "densidade_intermediario": jar.density("intermediario"),
        "densidade_tecnica": round(jar.density("avancado") + jar.density("intermediario"), 2),
        "nao_explicados": jar.unexplained,
        "analogias": jar.analogies,
        "numeros_sem_lastro": grd.ungrounded_numbers,
        "cobertura_ancoras": grd.coverage,
        "fatos_faltando": grd.missing,
    }

    if read.flesch is not None:
        lo, hi = target.get("flesch_min"), target.get("flesch_max")
        ok = (lo is None or read.flesch >= lo) and (hi is None or read.flesch <= hi)
        rng = (
            f"{'≥ ' + str(lo) if lo is not None else ''}{' e ' if lo and hi else ''}"
            f"{'≤ ' + str(hi) if hi is not None else ''}"
        )
        if lo is not None and read.flesch < lo:
            hint = "Use frases mais curtas e palavras mais simples."
        elif level == "avancado":
            hint = "Use a linguagem técnica plena do mercado, sem simplificar."
        else:
            hint = "Texto simples demais para o nível: frases um pouco mais elaboradas."
        report.checks.append(
            Check("legibilidade (Flesch-PT)", read.flesch, rng, ok, feedback=hint if not ok else "")
        )

    for nivel, max_n in (target.get("unexplained_max") or {}).items():
        terms = jar.unexplained.get(nivel, [])
        report.checks.append(
            Check(
                f"termos {nivel} sem explicação",
                len(terms),
                f"≤ {max_n}",
                len(terms) <= max_n,
                feedback=(
                    "Explique logo após o primeiro uso (aposto, 'ou seja', analogia): "
                    + ", ".join(terms)
                )
                if terms
                else "",
            )
        )

    if "analogies_min" in target:
        report.checks.append(
            Check(
                "analogias",
                jar.analogies,
                f"≥ {target['analogies_min']}",
                jar.analogies >= target["analogies_min"],
                feedback="Inclua uma analogia do cotidiano ('é como...').",
            )
        )
    if "analogies_max" in target:
        report.checks.append(
            Check(
                "analogias",
                jar.analogies,
                f"≤ {target['analogies_max']}",
                jar.analogies <= target["analogies_max"],
                feedback="Público avançado: retire analogias didáticas.",
            )
        )
    if "technical_density_min" in target:
        dens = round(jar.density("avancado") + jar.density("intermediario"), 2)
        report.checks.append(
            Check(
                "densidade técnica (interm.+avanç.)",
                dens,
                f"≥ {target['technical_density_min']}/100 pal.",
                dens >= target["technical_density_min"],
                feedback="Preserve o jargão técnico pleno; não simplifique para o avançado.",
            )
        )

    report.checks.append(
        Check(
            "números sem lastro na fonte",
            grd.ungrounded_numbers or 0,
            "nenhum",
            not grd.ungrounded_numbers,
            hard=True,
            feedback=(
                "Use apenas números presentes nas âncoras; remova: "
                + ", ".join(n.lstrip("#") for n in grd.ungrounded_numbers)
            )
            if grd.ungrounded_numbers
            else "",
        )
    )
    report.checks.append(
        Check(
            "cobertura dos fatos centrais",
            grd.coverage,
            f"≥ {target['anchor_coverage_min']}",
            grd.coverage >= target["anchor_coverage_min"],
            feedback=("Inclua os fatos: " + ", ".join(grd.missing)) if grd.missing else "",
        )
    )
    report.checks += _format_checks(fmt, content, cfg)
    return report

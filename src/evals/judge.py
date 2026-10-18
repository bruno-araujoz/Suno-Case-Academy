"""Structured LLM judge — ONLY for non-numeric claims (numbers are checked by code).

Unlike a generic "rate this text 1-10" judge (complacency and length bias, the TAPI's critique),
it returns a verdict per claim against the verified anchors, with temperature 0. Optional: the
evaluator works without it; enabled per run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from generation.schemas import Anchors
from llm.prompts import load_prompt
from llm.router import LLMRouter


class Claim(BaseModel):
    afirmacao: str
    veredito: Literal["apoiada", "nao_apoiada"]
    motivo: str = Field(max_length=200)


class JudgeResult(BaseModel):
    afirmacoes: list[Claim] = Field(max_length=12)

    @property
    def unsupported(self) -> list[Claim]:
        return [c for c in self.afirmacoes if c.veredito == "nao_apoiada"]


def anchors_listing(anchors: Anchors) -> str:
    lines = [f"Evento: {anchors.evento}", f"Contexto: {anchors.contexto}"]
    lines += [f"{f.id}: {f.afirmacao}" for f in anchors.fatos]
    lines += [f"Implicação: {i}" for i in anchors.implicacoes]
    return "\n".join(lines)


async def judge(router: LLMRouter, text: str, anchors: Anchors) -> JudgeResult:
    prompt = load_prompt("judge")
    result, _ = await router.generate(
        JudgeResult,
        [{"role": "user", "content": prompt.render(fatos=anchors_listing(anchors), texto=text)}],
        purpose="judge",
        prompt_version=prompt.version,
        temperature=0.0,
        max_tokens=2500,
    )
    return result

"""LangGraph workflow for one request (format + level).

refresh → select_event → check_cache ─(cached)→ END
                              └→ anchor → brief → write → evaluate ─(failed & attempts < max)→ write
                                                                    └→ persist → END

Nodes stream their progress (`stream_mode="updates"`) so the UI can show each step live.
Only `anchor` and `write` (and the optional judge) call an LLM; everything else is code.
"""

from __future__ import annotations

import hashlib
import json
import operator
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from evals.evaluator import EvalReport, add_judge_check, evaluate, level_targets
from evals.judge import judge
from glossary.matcher import Glossary
from llm.prompts import load_prompt
from llm.router import LLMRouter
from scraper.core.config import Settings
from scraper.core.db import Database
from scraper.core.http import HttpClient
from scraper.core.logging import get_logger
from scraper.enrich.enricher import enrich_documents
from scraper.enrich.pool import CpuPool
from scraper.ondemand import ensure_fresh

from .anchoring import extract_anchors
from .brief import AUDIENCE, Brief, anchors_text, build_brief, targets_text
from .evidence import EvidenceDoc, build_evidence, docs_hash
from .schemas import SCHEMAS, Anchors, Format, Level, reader_text

log = get_logger("generation")

MAX_ATTEMPTS = 3


class NoEventError(RuntimeError):
    pass


@dataclass
class GenDeps:
    db: Database
    router: LLMRouter
    glossary: Glossary
    settings: Settings
    http: HttpClient
    refresh: bool = True
    refresh_budget_s: float = 20.0
    force: bool = False
    use_judge: bool = False
    # Demo of the reflection loop (TAPI deliverable 3): the 1st write deliberately ignores the
    # audience adaptation, so the evaluator rejects it and the rewrite shows the correction.
    demo_reflection: bool = False
    event: str | None = None  # cluster_id chosen explicitly
    topic: str | None = None  # free-text topic the user searched (provenance only)
    window_hours: int = 48
    levels_cfg: dict[str, Any] = field(default_factory=level_targets)


class GenState(TypedDict, total=False):
    fmt: Format
    level: Level
    started: float
    refresh: dict[str, Any]
    cluster_id: str
    event_title: str
    publishers: int
    evidence: list[EvidenceDoc]
    prompt_versions: str
    cached: dict[str, Any] | None
    anchors_id: int
    anchors: Anchors
    dropped: list[dict]
    brief: Brief
    attempts: Annotated[list[dict[str, Any]], operator.add]  # one per `write`
    evals: Annotated[list[dict[str, Any]], operator.add]  # one per `evaluate`, same order
    generation_id: int


def levels_version() -> str:
    from evals.evaluator import LEVELS_FILE

    return "levels@" + hashlib.sha256(LEVELS_FILE.read_bytes()).hexdigest()[:10]


def prompt_versions(fmt: Format, use_judge: bool, demo: bool = False) -> str:
    """Cache key + provenance: prompts AND the level targets the output was evaluated against."""
    parts = [
        levels_version(),
        load_prompt("anchor").version,
        load_prompt(f"write_{fmt}").version,
        load_prompt("write_common").version,
    ]
    if use_judge:
        parts.append(load_prompt("judge").version)
    if demo:
        parts.append("demo-reflection")  # separate cache entries from normal generations
    return "+".join(parts)


def build_graph(deps: GenDeps):
    async def refresh(state: GenState) -> dict:
        if not deps.refresh:
            return {"refresh": {"skipped": True}}
        report = await ensure_fresh(deps.db, budget_s=deps.refresh_budget_s, http=deps.http)
        return {
            "refresh": {
                "due": report.due,
                "ran": report.ran,
                "timed_out": report.timed_out,
                "locked_by_other": report.locked_by_other,
                "duration_s": report.duration_s,
            }
        }

    async def select_event(state: GenState) -> dict:
        if deps.event:
            info = await deps.db.event_info(deps.event)
            candidates = [info] if info else []
        else:
            candidates = await deps.db.top_events(deps.window_hours)
        for event in candidates:
            docs = await deps.db.cluster_documents(event["cluster_id"])
            need = [
                d.url_hash
                for d in docs
                if d.status == "pending_enrich"
                or d.needs_enrichment(deps.settings.min_content_chars)
            ]
            if need:  # on-demand enrichment: only this event's documents
                docs = await enrich_documents(
                    deps.db, deps.http, CpuPool(0), deps.settings, [d.url_hash for d in docs]
                )
            evidence = build_evidence(docs, deps.glossary)
            if evidence:
                return {
                    "cluster_id": event["cluster_id"],
                    "event_title": event["title"],
                    "publishers": int(event["publishers"] or 1),
                    "evidence": evidence,
                    "prompt_versions": prompt_versions(
                        state["fmt"], deps.use_judge, deps.demo_reflection
                    ),
                }
        raise NoEventError(
            "nenhum evento com material suficiente na janela "
            f"de {deps.window_hours}h (rode `scrape.py refresh`)"
        )

    async def check_cache(state: GenState) -> dict:
        if deps.force:
            return {"cached": None}
        row = await deps.db.find_generation(
            state["cluster_id"], state["fmt"], state["level"], state["prompt_versions"]
        )
        return {"cached": dict(row) if row else None}

    async def anchor(state: GenState) -> dict:
        evidence = state["evidence"]
        version = load_prompt("anchor").version
        dhash = docs_hash(evidence)
        cached = await deps.db.get_anchors(state["cluster_id"], dhash, version)
        if cached and not deps.force:
            return {
                "anchors_id": cached["id"],
                "anchors": Anchors.model_validate(json.loads(cached["anchors"])),
                "dropped": json.loads(cached["dropped"]),
            }
        result = await extract_anchors(deps.router, evidence)
        anchors_id = await deps.db.save_anchors(
            state["cluster_id"],
            dhash,
            version,
            result.anchors.model_dump(),
            [e.public() for e in evidence],
            result.dropped,
            result.call.provider if result.call else None,
            result.call.model if result.call else None,
        )
        return {"anchors_id": anchors_id, "anchors": result.anchors, "dropped": result.dropped}

    async def brief(state: GenState) -> dict:
        suggest = deps.levels_cfg.get("avancado", {}).get("suggest_vocabulary", True)
        return {"brief": build_brief(state["level"], state["anchors"], deps.glossary, suggest)}

    async def write(state: GenState) -> dict:
        fmt, level = state["fmt"], state["level"]
        attempts = state.get("attempts") or []
        evals = state.get("evals") or []
        revisao = ""
        if attempts:
            revisao = (
                "\nREVISÃO: a versão anterior (JSON abaixo) foi REPROVADA nestas métricas:\n"
                f"{evals[-1]['feedback']}\nReescreva corrigindo exatamente esses pontos e "
                "mantendo o que estava bom.\nVERSÃO ANTERIOR:\n"
                f"{json.dumps(attempts[-1]['content'], ensure_ascii=False)}"
            )
        b: Brief = state["brief"]
        publico, explicar = AUDIENCE[level], b.explain_text()
        metas = targets_text(level, deps.levels_cfg, fmt)
        if deps.demo_reflection and not attempts and level != "avancado":
            # Deliberately unadapted first draft (written for the advanced reader).
            publico, explicar = AUDIENCE["avancado"], "(nenhum)"
            metas = targets_text("avancado", deps.levels_cfg, fmt)
        comum = load_prompt("write_common").render(
            publico=publico,
            fatos=anchors_text(state["anchors"]),
            termos_explicar=explicar,
            termos_livres=b.free_text(),
            termos_tecnicos=b.suggest_text()
            if not (deps.demo_reflection and not attempts and level != "avancado")
            else "(não se aplica)",
            metas=metas,
            revisao=revisao,
        )
        prompt = load_prompt(f"write_{fmt}")
        started = time.perf_counter()
        content, call = await deps.router.generate(
            SCHEMAS[fmt],
            [{"role": "user", "content": prompt.render(comum=comum)}],
            purpose="write",
            prompt_version=state["prompt_versions"],
            temperature=0.4,
            max_tokens=3500,
        )
        return {
            "attempts": [
                {
                    "n": len(attempts) + 1,
                    "content": content.model_dump(),
                    "model_obj": content,
                    "provider": call.provider,
                    "model": call.model,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                }
            ]
        }

    async def evaluate_node(state: GenState) -> dict:
        content: BaseModel = state["attempts"][-1]["model_obj"]
        report: EvalReport = evaluate(
            state["fmt"], state["level"], content, state["anchors"], deps.glossary, deps.levels_cfg
        )
        if deps.use_judge:
            add_judge_check(
                report,
                await judge(deps.router, reader_text(state["fmt"], content), state["anchors"]),
            )
        return {
            "evals": [
                {
                    "report": report,
                    "eval": report.as_dict(),
                    "feedback": report.feedback(),
                    "passed": report.passed,
                    "score": report.score,
                }
            ]
        }

    async def persist(state: GenState) -> dict:
        attempts = [{**a, **e} for a, e in zip(state["attempts"], state["evals"], strict=True)]
        best = max(attempts, key=lambda a: (a["score"], a["passed"], -a["n"]))
        row = {
            "cluster_id": state["cluster_id"],
            "event_title": state["event_title"],
            "fmt": state["fmt"],
            "level": state["level"],
            "prompt_versions": state["prompt_versions"],
            "anchors_id": state["anchors_id"],
            "content": best["content"],
            "eval": best["eval"],
            "passed": best["passed"],
            "score": best["score"],
            "attempts": len(attempts),
            "best_attempt": best["n"],
            "latency_ms": int((time.perf_counter() - state["started"]) * 1000),
            "topic": deps.topic,
        }
        gen_id = await deps.db.save_generation(
            row,
            [
                {k: a[k] for k in ("n", "content", "eval", "provider", "model", "latency_ms")}
                for a in attempts
            ],
        )
        return {"generation_id": gen_id}

    def after_cache(state: GenState) -> str:
        return END if state.get("cached") else "anchor"

    def after_evaluate(state: GenState) -> str:
        last = state["evals"][-1]
        return "persist" if last["passed"] or len(state["evals"]) >= MAX_ATTEMPTS else "write"

    graph = StateGraph(GenState)
    for name, fn in [
        ("refresh", refresh),
        ("select_event", select_event),
        ("check_cache", check_cache),
        ("anchor", anchor),
        ("brief", brief),
        ("write", write),
        ("evaluate", evaluate_node),
        ("persist", persist),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "refresh")
    graph.add_edge("refresh", "select_event")
    graph.add_edge("select_event", "check_cache")
    graph.add_conditional_edges("check_cache", after_cache, {"anchor": "anchor", END: END})
    graph.add_edge("anchor", "brief")
    graph.add_edge("brief", "write")
    graph.add_edge("write", "evaluate")
    graph.add_conditional_edges(
        "evaluate", after_evaluate, {"write": "write", "persist": "persist"}
    )
    graph.add_edge("persist", END)
    return graph.compile()

"""Run one generation request end to end (used by the CLI, the UI and the batch suite)."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from glossary.matcher import Glossary, load_glossary
from llm.router import LLMRouter, db_recorder
from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.http import HttpClient

from .graph import GenDeps, GenState, build_graph
from .schemas import Format, Level

ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]

NODE_LABELS = {
    "refresh": "Atualizando fontes vencidas",
    "select_event": "Escolhendo o evento mais relevante",
    "check_cache": "Verificando cache",
    "anchor": "Extraindo e verificando os fatos (âncoras)",
    "brief": "Montando as instruções do nível",
    "write": "Escrevendo",
    "evaluate": "Avaliando com métricas",
    "persist": "Salvando",
}


@dataclass
class GenerationResult:
    fmt: Format
    level: Level
    cluster_id: str
    event_title: str
    publishers: int
    content: dict[str, Any]
    eval: dict[str, Any]
    passed: bool
    score: float
    attempts: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    anchors: dict[str, Any] = field(default_factory=dict)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    refresh: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    generation_id: int | None = None
    latency_ms: int = 0
    glossary_reviewed: bool = False
    demo_reflection: bool = False
    topic: str | None = None


async def _from_cache(db: Database, state: GenState, row: dict) -> GenerationResult:
    attempts = [
        {
            "n": a["n"],
            "content": json.loads(a["content"]),
            "eval": json.loads(a["eval"]),
            "provider": a["provider"],
            "model": a["model"],
            "latency_ms": a["latency_ms"],
        }
        for a in await db.generation_attempts(row["id"])
    ]
    async with db.pool.acquire() as conn:
        anchors_row = await conn.fetchrow(
            "SELECT anchors, evidence, dropped FROM anchors WHERE id=$1", row["anchors_id"]
        )
    return GenerationResult(
        fmt=row["fmt"],
        level=row["level"],
        cluster_id=row["cluster_id"],
        event_title=row["event_title"],
        publishers=state.get("publishers", 1),
        content=json.loads(row["content"]),
        eval=json.loads(row["eval"]),
        passed=row["passed"],
        score=row["score"],
        attempts=attempts,
        evidence=json.loads(anchors_row["evidence"]) if anchors_row else [],
        anchors=json.loads(anchors_row["anchors"]) if anchors_row else {},
        dropped=json.loads(anchors_row["dropped"]) if anchors_row else [],
        refresh=state.get("refresh", {}),
        cached=True,
        generation_id=row["id"],
        latency_ms=row["latency_ms"] or 0,
        topic=row.get("topic"),
        demo_reflection="demo-reflection" in (row.get("prompt_versions") or ""),
    )


async def load_generation(db: Database, generation_id: int) -> GenerationResult | None:
    """A stored generation with its attempts, anchors and evidence (history / detail views)."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generations WHERE id=$1", generation_id)
    if row is None:
        return None
    result = await _from_cache(db, {}, dict(row))
    result.cached = False  # loaded from history, not served as a cache hit
    return result


def describe_progress(node: str, update: dict[str, Any]) -> dict[str, Any]:
    """Human label + structured detail for one graph step (CLI, API/SSE)."""
    info: dict[str, Any] = {"node": node, "label": NODE_LABELS.get(node, node)}
    if node == "refresh" and update.get("refresh"):
        r = update["refresh"]
        info["detail"] = (
            "pulado"
            if r.get("skipped")
            else f"{len(r['due'])} fontes vencidas em {r.get('duration_s')}s"
            if r.get("due")
            else "tudo dentro da validade"
        )
    elif node == "select_event" and "event_title" in update:
        info["detail"] = update["event_title"]
        info["publishers"] = update.get("publishers")
        info["cluster_id"] = update.get("cluster_id")
    elif node == "check_cache":
        info["detail"] = (
            "resultado em cache — 0 chamadas de LLM" if update.get("cached") else "nada em cache"
        )
        info["cached"] = bool(update.get("cached"))
    elif node == "anchor" and update.get("anchors") is not None:
        anchors = update["anchors"]
        info["detail"] = f"{len(anchors.fatos)} fatos verificados" + (
            f", {len(update.get('dropped') or [])} descartados" if update.get("dropped") else ""
        )
    elif node == "brief" and update.get("brief") is not None:
        b = update["brief"]
        info["detail"] = f"{len(b.explain)} termos a explicar, {len(b.free)} livres"
    elif node == "write" and update.get("attempts"):
        a = update["attempts"][-1]
        info["detail"] = f"tentativa {a['n']} via {a['provider']}"
        info["attempt"] = a["n"]
    elif node == "evaluate" and update.get("evals"):
        e = update["evals"][-1]
        info["detail"] = f"{'aprovado' if e['passed'] else 'reprovado'} · score {e['score']}"
        info["passed"], info["score"] = e["passed"], e["score"]
        info["failures"] = [c.name for c in e["report"].failures()]
    return info


async def generate(
    fmt: Format,
    level: Level,
    *,
    db: Database,
    router: LLMRouter | None = None,
    http: HttpClient | None = None,
    refresh: bool = True,
    force: bool = False,
    use_judge: bool = False,
    event: str | None = None,
    on_progress: ProgressCallback | None = None,
    glossary: Glossary | None = None,
    demo_reflection: bool = False,
    topic: str | None = None,
) -> GenerationResult:
    settings = get_settings()
    own_http = http is None
    http = http or HttpClient(settings)
    router = router or LLMRouter(settings, http=http, recorder=db_recorder(db))
    glossary = glossary or load_glossary(True)
    deps = GenDeps(
        db=db,
        router=router,
        glossary=glossary,
        settings=settings,
        http=http,
        refresh=refresh,
        force=force,
        use_judge=use_judge,
        event=event,
        demo_reflection=demo_reflection,
        topic=topic,
    )
    graph = build_graph(deps)
    state: GenState = {
        "fmt": fmt,
        "level": level,
        "started": time.perf_counter(),
        "attempts": [],
        "evals": [],
    }
    try:
        async for mode, chunk in graph.astream(state, stream_mode=["updates", "values"]):
            if mode == "values":
                state = chunk
            elif on_progress is not None:
                for node, update in chunk.items():
                    result = on_progress(node, update or {})
                    if hasattr(result, "__await__"):
                        await result
    finally:
        if own_http:
            await http.aclose()

    if state.get("cached"):
        return await _from_cache(db, state, state["cached"])
    attempts = [
        {
            **{k: v for k, v in a.items() if k != "model_obj"},
            **{k: v for k, v in e.items() if k != "report"},
        }
        for a, e in zip(state["attempts"], state["evals"], strict=True)
    ]
    best = max(attempts, key=lambda a: (a["score"], a["passed"], -a["n"]))
    return GenerationResult(
        fmt=fmt,
        level=level,
        cluster_id=state["cluster_id"],
        event_title=state["event_title"],
        publishers=state.get("publishers", 1),
        content=best["content"],
        eval=best["eval"],
        passed=best["passed"],
        score=best["score"],
        attempts=attempts,
        evidence=[e.public() for e in state["evidence"]],
        anchors=state["anchors"].model_dump(),
        dropped=state.get("dropped", []),
        refresh=state.get("refresh", {}),
        cached=False,
        generation_id=state.get("generation_id"),
        latency_ms=int((time.perf_counter() - state["started"]) * 1000),
        glossary_reviewed=all(t.revisado for t in glossary.terms),
        demo_reflection=demo_reflection,
        topic=topic,
    )

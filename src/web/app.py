"""Suno Content — web API (FastAPI) + minimalist front end.

  uv run uvicorn web.app:app --port 8000      →  http://localhost:8000

Unlike Streamlit (which re-runs the whole script on every interaction), the page is a static
single-page app: it calls this JSON API with `fetch` and receives the generation progress as
Server-Sent Events. Database pool, HTTP client and LLM router are created once (lifespan) and
shared by all requests — so rate-limit buckets and caches are shared too.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from evals.evaluator import level_targets
from generation.graph import NoEventError
from generation.service import describe_progress, generate, load_generation
from glossary.matcher import load_glossary
from llm.router import LLMError, LLMRouter, db_recorder
from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.http import HttpClient
from scraper.core.logging import get_logger, setup_logging
from topics.service import find_topic

log = get_logger("web")
STATIC = Path(__file__).resolve().parent / "static"
REPORTS = Path(__file__).resolve().parents[2] / "reports"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("WARNING")
    settings = get_settings()
    db = await Database(settings).connect()
    await db.migrate()
    http = HttpClient(settings)
    app.state.db = db
    app.state.http = http
    app.state.router = LLMRouter(settings, http=http, recorder=db_recorder(db))
    app.state.glossary = load_glossary(True)
    try:
        yield
    finally:
        await http.aclose()
        await db.close()


app = FastAPI(
    title="Suno Content", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
)


def _jsonable(value: Any) -> Any:
    """Dataclasses/datetimes/Decimals → plain JSON values."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


# ------------------------------------------------------------------ read endpoints


@app.get("/api/health")
async def health(request: Request) -> dict[str, Any]:
    state = request.app.state
    async with state.db.pool.acquire() as conn:
        docs = await conn.fetchval("SELECT count(*) FROM documents")
    providers = [
        f"{p.name}/{p.model}" for p in state.router.providers if p.key or p.name == "ollama"
    ]
    return {
        "ok": True,
        "documents": docs,
        "llm_providers": providers,
        "glossary_terms": len(state.glossary.terms),
        "glossary_reviewed": all(t.revisado for t in state.glossary.terms),
    }


@app.get("/api/events")
async def events(
    request: Request, window: int = Query(48, ge=6, le=24 * 30), limit: int = Query(6, ge=1, le=20)
) -> list[dict[str, Any]]:
    rows = await request.app.state.db.top_events(window, limit=limit)
    return _jsonable([dict(r) for r in rows])


@app.get("/api/topics/search")
async def topics_search(
    request: Request, q: str = Query(..., min_length=2, max_length=120), expand: bool = False
) -> dict[str, Any]:
    state = request.app.state
    result = await find_topic(state.db, state.http, q, expand=expand)
    return _jsonable(asdict(result))


@app.get("/api/generations")
async def generations(request: Request, limit: int = Query(30, ge=1, le=200)):
    async with request.app.state.db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, created_at, fmt, level, topic, event_title, passed, score, attempts, "
            "latency_ms, prompt_versions LIKE '%demo-reflection%' AS demo "
            "FROM generations ORDER BY id DESC LIMIT $1",
            limit,
        )
    return _jsonable([dict(r) for r in rows])


@app.get("/api/generations/{generation_id}")
async def generation_detail(request: Request, generation_id: int) -> dict[str, Any]:
    result = await load_generation(request.app.state.db, generation_id)
    if result is None:
        raise HTTPException(404, "geração não encontrada")
    return _jsonable(asdict(result))


@app.get("/api/levels")
async def levels() -> dict[str, Any]:
    return level_targets()


def _read_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data.get("rows", []):  # keep the payload light: drop full contents
        row.pop("content", None)
        row.pop("features", None)
    data["id"] = path.parent.name
    return data


def _report_summary(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    levels = sorted({r["level"] for r in rows})
    return {
        "id": path.parent.name,
        "generated_at": data.get("generated_at"),
        "generations": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "levels": levels,
        "complete": len(levels) == 3,
        "judge": bool((data.get("judge") or {}).get("checked"))
        or any("afirmacoes_nao_apoiadas" in r.get("metrics", {}) for r in rows),
    }


@app.get("/api/reports")
async def reports() -> list[dict[str, Any]]:
    files = sorted(REPORTS.glob("*/report.json"), reverse=True)
    return await asyncio.to_thread(lambda: [_report_summary(f) for f in files])


@app.get("/api/reports/latest")
async def latest_report() -> dict[str, Any]:
    """Newest COMPLETE batch (all three levels); partial A/B runs are listed in /api/reports."""
    files = sorted(REPORTS.glob("*/report.json"), reverse=True)
    if not files:
        raise HTTPException(404, "nenhum relatório ainda (rode evaluate.py batch)")
    summaries = await asyncio.to_thread(lambda: [_report_summary(f) for f in files])
    chosen = next((f for f, s in zip(files, summaries, strict=True) if s["complete"]), files[0])
    return await asyncio.to_thread(_read_report, chosen)


@app.get("/api/reports/{report_id}")
async def report_by_id(report_id: str) -> dict[str, Any]:
    path = REPORTS / report_id / "report.json"
    if not report_id.replace("T", "").isdigit() or not path.exists():
        raise HTTPException(404, "relatório não encontrado")
    return await asyncio.to_thread(_read_report, path)


# ------------------------------------------------------------------ generation (SSE)


class GenerateOptions(BaseModel):
    refresh: bool = True
    force: bool = False
    judge: bool = False
    demo_reflection: bool = False


class GenerateRequest(BaseModel):
    fmt: Literal["artigo", "carrossel", "roteiro"]
    level: Literal["iniciante", "intermediario", "avancado"]
    cluster_id: str | None = Field(None, description="evento escolhido; vazio = o mais relevante")
    topic: str | None = Field(None, max_length=120, description="tema digitado (rastreabilidade)")
    options: GenerateOptions = Field(default_factory=GenerateOptions)


@app.post("/api/generate", response_class=EventSourceResponse)
async def generate_stream(
    request: Request, body: GenerateRequest
) -> AsyncIterable[ServerSentEvent]:
    """Runs the graph and streams `progress` events, then `result` (or `error`)."""
    state = request.app.state
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_progress(node: str, update: dict[str, Any]) -> None:
        queue.put_nowait(_jsonable(describe_progress(node, update)))

    task = asyncio.create_task(
        generate(
            body.fmt,
            body.level,
            db=state.db,
            router=state.router,
            http=state.http,
            refresh=body.options.refresh,
            force=body.options.force,
            use_judge=body.options.judge,
            event=body.cluster_id,
            on_progress=on_progress,
            glossary=state.glossary,
            demo_reflection=body.options.demo_reflection,
            topic=body.topic,
        )
    )
    try:
        while not task.done() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.25)
            except TimeoutError:
                if await request.is_disconnected():
                    task.cancel()
                    return
                continue
            yield ServerSentEvent(data=item, event="progress")
        try:
            result = task.result()
        except (NoEventError, LLMError, ValueError) as exc:
            yield ServerSentEvent(data={"message": str(exc)}, event="error")
            return
        except Exception as exc:  # unexpected: report instead of breaking the stream
            log.exception("geração falhou")
            yield ServerSentEvent(
                data={"message": f"erro interno: {type(exc).__name__}"}, event="error"
            )
            return
        yield ServerSentEvent(data=_jsonable(asdict(result)), event="result")
    finally:
        if not task.done():
            task.cancel()


# ------------------------------------------------------------------ front end (last: API first)


@app.middleware("http")
async def revalidate_static(request: Request, call_next):
    """No build step = no hashed file names: make browsers revalidate (ETag) on every load."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.mount("/", StaticFiles(directory=STATIC, html=True), name="front")

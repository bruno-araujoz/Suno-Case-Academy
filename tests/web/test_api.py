"""Web API: JSON endpoints and the SSE generation stream (real test DB, mocked LLM)."""

import json

import httpx
import pytest

from tests.generation.test_graph import GOOD, G, llm, seed
from web.app import app

pytestmark = pytest.mark.db


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        name, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if data:
            events.append((name, json.loads(data)))
    return events


@pytest.fixture
async def client(db):
    await seed(db)
    router, http = llm([])
    app.state.db, app.state.http, app.state.router, app.state.glossary = db, http, router, G
    transport = httpx.ASGITransport(app=app)  # lifespan not run: state injected above
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await http.aclose()


async def test_health_events_and_search(client):
    health = (await client.get("/api/health")).json()
    assert health["ok"] and health["documents"] == 1 and health["glossary_terms"] == 3
    events = (await client.get("/api/events")).json()
    assert events[0]["cluster_id"] == "c1"
    found = (await client.get("/api/topics/search", params={"q": "Copom Selic"})).json()
    assert found["events"][0]["cluster_id"] == "c1" and not found["expanded"]
    assert (await client.get("/api/topics/search", params={"q": "x"})).status_code == 422


async def test_generate_streams_progress_then_result_and_history(client):
    body = {
        "fmt": "carrossel",
        "level": "iniciante",
        "topic": "Copom",
        "options": {"refresh": False},
    }
    response = await client.post("/api/generate", json=body)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [n for n, _ in events]
    assert names[-1] == "result" and names.count("progress") >= 7
    nodes = [d["node"] for n, d in events if n == "progress"]
    assert nodes[:3] == ["refresh", "select_event", "check_cache"] and "evaluate" in nodes
    evaluations = [d for n, d in events if n == "progress" and d["node"] == "evaluate"]
    assert [e["passed"] for e in evaluations] == [False, True]
    result = events[-1][1]
    assert result["passed"] and result["content"] == GOOD and result["topic"] == "Copom"

    history = (await client.get("/api/generations")).json()
    assert history[0]["topic"] == "Copom" and history[0]["attempts"] == 2
    detail = (await client.get(f"/api/generations/{history[0]['id']}")).json()
    assert len(detail["attempts"]) == 2 and detail["anchors"]["fatos"]
    assert (await client.get("/api/generations/999999")).status_code == 404


async def test_generate_error_event_when_no_event(client):
    body = {
        "fmt": "artigo",
        "level": "avancado",
        "cluster_id": "nao-existe",
        "options": {"refresh": False},
    }
    events = parse_sse((await client.post("/api/generate", json=body)).text)
    assert events[-1][0] == "error" and "nenhum evento" in events[-1][1]["message"]


async def test_front_is_served(client):
    page = await client.get("/")
    assert page.status_code == 200 and "Suno Content" in page.text


async def test_reports_prefer_complete_batches(client, tmp_path, monkeypatch):
    import web.app as web_app

    def write(name, levels):
        d = tmp_path / name
        d.mkdir()
        rows = [{"level": lvl, "passed": True, "metrics": {}} for lvl in levels]
        (d / "report.json").write_text(json.dumps({"generated_at": name, "rows": rows}))

    write("20261001T000000", ["iniciante", "intermediario", "avancado"])
    write("20261002T000000", ["avancado"])  # newer, but partial (A/B run)
    monkeypatch.setattr(web_app, "REPORTS", tmp_path)
    listing = (await client.get("/api/reports")).json()
    assert [r["complete"] for r in listing] == [False, True]
    assert (await client.get("/api/reports/latest")).json()["id"] == "20261001T000000"
    assert (await client.get("/api/reports/20261002T000000")).json()["id"] == "20261002T000000"
    assert (await client.get("/api/reports/..%2Fetc")).status_code == 404

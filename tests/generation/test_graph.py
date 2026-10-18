"""End-to-end generation graph with a real database and a mocked LLM (no network)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from generation.service import generate
from glossary.matcher import Glossary, Term
from llm.router import LLMRouter, Provider
from scraper.core.http import HttpClient
from scraper.core.models import Document

pytestmark = pytest.mark.db

ATA = (
    "O Comitê de Política Monetária (Copom) decidiu reduzir a taxa Selic para 13,75% a.a. "
    "O Comitê avalia que o hiato do produto segue positivo e que as expectativas desancoradas "
    "exigem cautela. A decisão é compatível com a convergência da inflação à meta. " * 3
)
G = Glossary(
    [
        Term("Selic", "intermediario", definicao="taxa básica de juros"),
        Term(
            "hiato do produto",
            "avancado",
            definicao="folga da economia",
            analogia="carro acima da velocidade",
        ),
        Term("expectativas desancoradas", "avancado"),
    ]
)

ANCHORS = {
    "evento": "Copom reduz a Selic para 13,75%",
    "contexto": "Ciclo de cortes.",
    "fatos": [
        {
            "id": "F1",
            "afirmacao": "O Copom reduziu a Selic para 13,75% ao ano",
            "numeros": ["13,75%"],
            "doc_id": "D1",
            "citacao": "decidiu reduzir a taxa Selic para 13,75% a.a.",
            "central": True,
        },
        {
            "id": "F2",
            "afirmacao": "O hiato do produto segue positivo",
            "numeros": [],
            "doc_id": "D1",
            "citacao": "o hiato do produto segue positivo",
            "central": True,
        },
        {
            "id": "F3",
            "afirmacao": "Fato inventado",
            "numeros": ["99%"],
            "doc_id": "D1",
            "citacao": "texto que não existe no documento",
            "central": False,
        },
    ],
    "implicacoes": ["crédito mais barato"],
}


def slides(texts):
    roles = ["gancho"] + ["corpo"] * (len(texts) - 2) + ["conclusao"]
    return {
        "slides": [
            {"papel": r, "titulo": f"Slide {i}", "texto": t}
            for i, (r, t) in enumerate(zip(roles, texts, strict=True))
        ],
        "legenda": "Entenda o Copom.",
        "hashtags": ["#selic"],
    }


BAD = slides(
    [
        "O Copom cortou a Selic para 13,75%.",
        "O hiato do produto segue positivo.",
        "As expectativas desancoradas preocupam.",
        "O ciclo continua.",
        "Dados importam.",
        "Fique de olho.",
    ]
)
GOOD = slides(
    [
        "O Banco Central cortou a Selic, que é a taxa básica de juros, para 13,75%.",
        "O hiato do produto (a folga da economia) segue positivo. "
        "É como um carro acima da velocidade.",
        "As expectativas desancoradas, ou seja, quando as pessoas esperam mais inflação, "
        "preocupam.",
        "Por isso o corte é pequeno. O banco vai com calma e olha os dados.",
        "Assim o crédito fica um pouco mais barato. Comprar a prazo fica mais fácil.",
        "Fique de olho na próxima reunião. Ela pode trazer outro corte.",
    ]
)


async def seed(db):
    doc = Document(
        source="bcb_copom",
        doc_type="copom_ata",
        tier="official",
        url="https://bcb.test/ata/281",
        title="281ª Reunião do Copom",
        published_at=datetime.now(UTC) - timedelta(hours=3),
        content_text=ATA,
        extraction_level="api",
    )
    await db.upsert_documents([doc])
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE documents SET cluster_id='c1', relevance_score=0.9")


def llm(calls):
    writes = iter([BAD, GOOD])

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        calls.append(prompt)
        body = ANCHORS if "DOCUMENTOS:" in prompt else next(writes)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(body)}}],
                "usage": {"total_tokens": 100},
            },
        )

    http = HttpClient(transport=httpx.MockTransport(handler))
    return LLMRouter(http=http, providers=[Provider("groq", "m", "K", "k", 10**9)]), http


async def test_reflection_loop_persists_attempts_and_caches(db):
    await seed(db)
    calls = []
    router, http = llm(calls)
    progress = []
    result = await generate(
        "carrossel",
        "iniciante",
        db=db,
        router=router,
        http=http,
        refresh=False,
        glossary=G,
        on_progress=lambda node, update: progress.append(node),
    )

    assert progress[:5] == ["refresh", "select_event", "check_cache", "anchor", "brief"]
    assert progress.count("write") == 2 and progress[-1] == "persist"
    assert len(calls) == 3  # anchors + 2 writes
    assert "REPROVADA" in calls[2] and "hiato do produto" in calls[2]  # feedback injected

    assert [a["passed"] for a in result.attempts] == [False, True]
    assert result.passed and result.content == GOOD and result.cluster_id == "c1"
    assert [f["id"] for f in result.anchors["fatos"]] == ["F1", "F2"]  # F3 dropped (bad citation)
    assert "citação não encontrada" in result.dropped[0]["motivo"]
    assert result.evidence[0]["url"] == "https://bcb.test/ata/281"

    async with db.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM generation_attempts") == 2

    calls.clear()
    again = await generate(
        "carrossel", "iniciante", db=db, router=router, http=http, refresh=False, glossary=G
    )
    assert again.cached and calls == [] and again.content == GOOD
    assert len(again.attempts) == 2 and again.anchors["fatos"][0]["id"] == "F1"
    await http.aclose()


async def test_demo_reflection_first_draft_ignores_audience(db):
    await seed(db)
    calls = []
    router, http = llm(calls)
    result = await generate(
        "carrossel",
        "iniciante",
        db=db,
        router=router,
        http=http,
        refresh=False,
        glossary=G,
        demo_reflection=True,
    )
    first_write, rewrite = calls[1], calls[2]
    assert "Público AVANÇADO" in first_write and "(nenhum)" in first_write
    assert "Investidor INICIANTE" in rewrite and "hiato do produto: folga" in rewrite
    assert result.demo_reflection and [a["passed"] for a in result.attempts] == [False, True]
    async with db.pool.acquire() as conn:
        versions = await conn.fetchval("SELECT prompt_versions FROM generations")
    assert versions.endswith("+demo-reflection")
    await http.aclose()


def test_advanced_brief_suggests_topic_vocabulary():
    from generation.brief import build_brief
    from generation.schemas import Anchors

    g = Glossary(
        [
            Term("Selic", "intermediario", categoria="politica_monetaria"),
            Term("forward guidance", "avancado", categoria="politica_monetaria"),
            Term("taxa terminal", "avancado", categoria="politica_monetaria"),
            Term("covenants", "avancado", categoria="empresas_resultados"),
        ]
    )
    anchors = Anchors.model_validate(ANCHORS)
    adv = build_brief("avancado", anchors, g)
    assert {t.termo for t in adv.suggest} == {"forward guidance", "taxa terminal"}
    assert build_brief("iniciante", anchors, g).suggest == []

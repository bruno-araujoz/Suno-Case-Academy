"""Topic search over stored documents (Portuguese full text, accent-insensitive)."""

from datetime import UTC, datetime, timedelta

import pytest

from scraper.core.models import Document

pytestmark = pytest.mark.db


def doc(url, title, text, cluster, hours=2, tier="news", score=0.5):
    return Document(
        source="suno" if tier == "news" else "cvm_ipe",
        doc_type="news" if tier == "news" else "fato_relevante",
        tier=tier,
        url=url,
        title=title,
        content_text=text,
        published_at=datetime.now(UTC) - timedelta(hours=hours),
        relevance_score=score,
        cluster_id=cluster,
    )


async def seed(db):
    await db.upsert_documents(
        [
            doc(
                "https://a.test/1",
                "Petrobrás anuncia dividendos bilionários",
                "A estatal aprovou a distribuição de proventos aos acionistas.",
                "c-petro",
                score=0.7,
            ),
            doc(
                "https://b.test/2",
                "Petrobras: o que muda para o acionista",
                "Analistas comentam os dividendos da Petrobras.",
                "c-petro",
                score=0.6,
            ),
            doc(
                "https://c.test/3",
                "Copom mantém a Selic em 13,75%",
                "O Banco Central manteve a taxa básica de juros.",
                "c-copom",
                score=0.9,
            ),
            doc(
                "https://d.test/4",
                "Petrobras antiga",
                "Notícia velha sobre a Petrobras.",
                "c-old",
                hours=24 * 60,
            ),
            doc(
                "https://e.test/ao-vivo-hoje",
                "Ibovespa ao vivo: Petrobras sobe",
                "Acompanhe ao vivo a Petrobras.",
                "c-live",
            ),
        ]
    )


async def test_accent_insensitive_search_groups_by_cluster(db):
    await seed(db)
    results = await db.search_events("petrobrás")
    ids = [r["cluster_id"] for r in results]
    assert ids[0] == "c-petro" and results[0]["docs"] == 2
    assert "c-old" not in ids  # outside the window
    assert "c-live" not in ids  # live blogs excluded
    assert "«" in results[0]["snippet"]  # highlighted match


async def test_search_ranks_and_handles_no_match(db):
    await seed(db)
    assert (await db.search_events("selic juros"))[0]["cluster_id"] == "c-copom"
    assert await db.search_events("criptomoeda inexistente") == []


async def test_generation_topic_column_exists(db):
    async with db.pool.acquire() as conn:
        cols = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name='generations'"
            )
        }
    assert "topic" in cols

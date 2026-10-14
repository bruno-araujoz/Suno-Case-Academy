from datetime import UTC, datetime

import pytest

from scraper.core.db import SourceState
from scraper.core.models import Document

pytestmark = pytest.mark.db


def make(url="https://a.com/1", content="texto", status="ready"):
    return Document(
        source="s",
        doc_type="news",
        tier="news",
        url=url,
        title="Título",
        published_at="2026-09-22",
        content_text=content,
        status=status,
    )


async def test_migrate_is_idempotent(db):
    assert await db.migrate() == []


async def test_upsert_dedupes_and_updates_content(db):
    await db.upsert_documents([make(), make(url="https://a.com/1?utm_source=x")])
    await db.upsert_documents([make(content="texto novo")])
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT content_text FROM documents")
    assert [r["content_text"] for r in rows] == ["texto novo"]


async def test_known_hashes_include_pending_which_backlog_retries(db):
    await db.upsert_documents([make(), make(url="https://a.com/2", status="pending_enrich")])
    assert await db.known_url_hashes() == {make().url_hash, make(url="https://a.com/2").url_hash}
    pending = await db.pending_documents()
    assert [d.url for d in pending] == ["https://a.com/2"]


async def test_state_roundtrip_keeps_max_watermark(db):
    t1, t2 = datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 2, tzinfo=UTC)
    await db.save_state(SourceState("s", "feed", "https://a.com/feed", etag='"1"', watermark=t2))
    await db.save_state(SourceState("s", "feed", "https://a.com/feed", etag='"2"', watermark=t1))
    state = await db.get_state("s", "feed")
    assert state.etag == '"2"' and state.watermark == t2


async def test_health_baseline_median(db):
    for n in (10, 12, 14):
        await db.record_health("r", {"source": "s", "status": "ok", "items_seen": n})
    await db.record_health("r", {"source": "s", "status": "failed", "items_seen": 0})
    assert await db.health_baseline("s") == 12

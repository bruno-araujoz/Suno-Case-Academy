"""Shared fixtures: settings without delays, isolated test database (skipped if offline)."""

from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest

from scraper.core.config import Settings
from scraper.core.db import Database

FIXTURES = Path(__file__).parent / "fixtures"
TEST_DB = "suno_content_test"
ADMIN_DSN = os.environ.get("TEST_ADMIN_DSN", "postgres://postgres:postgres@localhost:5432/postgres")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        per_host_rps=1000,
        http_retries=3,
        retry_backoff=0.0,
        retry_after_cap=0.01,
        database_url=ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}",
    )


@pytest.fixture
async def db(settings: Settings):
    """Fresh schema per test in a dedicated database; skipped when Postgres is not running."""
    try:
        admin = await asyncpg.connect(ADMIN_DSN, timeout=3)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres indisponível ({exc}); rode `docker compose up -d db`.")
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", TEST_DB)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await admin.close()

    database = await Database(settings).connect()
    async with database.pool.acquire() as conn:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    await database.migrate()
    yield database
    await database.close()

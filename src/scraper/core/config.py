"""Central configuration loaded from the environment (.env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgres://postgres:postgres@localhost:5432/suno_content"

    # HTTP
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
    request_timeout: float = 20.0
    max_connections: int = 40
    per_host_rps: float = 2.0  # requests per second allowed per host
    # Hosts that tolerate more (bulk document downloads); host -> requests per second.
    per_host_rps_overrides: dict[str, float] = Field(
        default_factory=lambda: {"www.rad.cvm.gov.br": 4.0}
    )
    http_retries: int = 3
    retry_after_cap: float = 30.0  # never wait longer than this on 429/503
    retry_backoff: float = 0.5  # base of the exponential backoff (seconds)

    # Pipeline
    default_since_days: int = 90
    queue_size: int = 500
    enrich_workers: int = 2  # process pool size for CPU-bound work (PDF, trafilatura)
    batch_size: int = 200
    batch_flush_seconds: float = 2.0
    min_content_chars: int = 400  # below this, feed content counts as truncated

    # Self-healing
    stale_feed_days: float = 7.0  # newest entry older than this => feed considered frozen
    heal_enabled: bool = True
    heal_llm_enabled: bool = True  # L4 (needs the `browser` extra + an LLM key)

    # Relevance weights (lexical, tier, coverage, recency) and threshold
    relevance_weights: tuple[float, float, float, float] = (0.35, 0.25, 0.25, 0.15)
    relevance_half_life_hours: float = 48.0
    high_priority_threshold: float = 0.55

    # LLM (only used by the L4 healer); models checked against the providers on 2026-10-14.
    # "<litellm provider>|<ENV with the key>", fallback order;
    # entries whose ENV is unset are skipped. Ollama (local, no key) is the last resort.
    llm_providers: list[str] = Field(
        default_factory=lambda: [
            "openrouter/meta-llama/llama-3.3-70b-instruct|OPENROUTER_API_KEY_1",
            "openrouter/meta-llama/llama-3.3-70b-instruct|OPENROUTER_API_KEY_2",
            "groq/openai/gpt-oss-120b|GROQ_API_KEY",
            "groq/openai/gpt-oss-120b|GROQ_API_KEY_1",
            "groq/openai/gpt-oss-120b|GROQ_API_KEY_2",
            "gemini/gemini-3.5-flash|GEMINI_API_KEY",
            "gemini/gemini-3.5-flash-lite|GEMINI_API_KEY",  # most available in tests (2026-10-14)
            "gemini/gemini-2.5-flash|GEMINI_API_KEY",
            "ollama/llama3.2|",
        ]
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

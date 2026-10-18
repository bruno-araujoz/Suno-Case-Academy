"""Route structured LLM calls across providers/keys with failover and rate-limit awareness.

- Providers come from `Settings.llm_providers` ("<provider>/<model>|<ENV>"); keys from .env.
- Every call asks for strict JSON-schema output and is validated with Pydantic; one repair
  round on invalid output, then the next provider.
- Small requests prefer Groq (fast); large ones (> `large_threshold` tokens) prefer Gemini
  (large context). Free tiers measured 2026-10-14: Groq 8k tokens/min per key, Gemini ~250 req/day.
- A per-key token bucket is fed by `x-ratelimit-*` headers, so a key known to be exhausted is
  skipped instead of hit with a 429.
- 429 / 5xx / network errors → next provider. Each attempt is reported to `recorder`.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from scraper.core.config import Settings, get_settings
from scraper.core.http import HttpClient
from scraper.core.logging import get_logger
from scraper.core.secrets import secrets

from .schema import strict_json_schema

log = get_logger("llm")

T = TypeVar("T", bound=BaseModel)

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "ollama": "http://localhost:11434/v1/chat/completions",
}
# Tokens/minute assumed before a provider tells us (headers). Groq's is measured; others generous.
DEFAULT_TPM = {"groq": 8_000, "gemini": 250_000, "openrouter": 50_000, "ollama": 10**9}
REASONING_PROVIDERS = {"groq", "gemini"}
DOWN_5XX_S = 120.0
DOWN_CONNECT_S = 600.0
_DURATION = re.compile(r"(?:(\d+)m)?(?:([\d.]+)s)?(?:(\d+)ms)?$")


class LLMError(RuntimeError):
    pass


@dataclass
class CallInfo:
    provider: str
    model: str
    key_label: str | None
    purpose: str
    prompt_version: str | None
    in_tokens: int | None = None
    out_tokens: int | None = None
    latency_ms: int = 0
    ok: bool = False
    error: str | None = None
    repaired: bool = False


Recorder = Callable[[CallInfo], Awaitable[None]]


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    return sum(len(m.get("content", "")) for m in messages) // 4 + 50


def _parse_reset(value: str | None) -> float:
    """'22.11s' | '1m26.4s' | '120ms' → seconds."""
    if not value:
        return 60.0
    m = _DURATION.match(value.strip())
    if not m:
        return 60.0
    minutes, seconds, millis = m.groups()
    return int(minutes or 0) * 60 + float(seconds or 0) + int(millis or 0) / 1000


@dataclass
class Provider:
    name: str
    model: str
    key_label: str | None
    key: str | None
    tpm: int
    remaining: float = field(init=False)
    refill_at: float = 0.0  # monotonic time when the bucket is known to be full again
    down_until: float = 0.0  # provider unavailable (503 / connection refused) until then

    def __post_init__(self) -> None:
        self.remaining = float(self.tpm)

    @property
    def url(self) -> str:
        return ENDPOINTS[self.name]

    def is_down(self, now: float) -> bool:
        return now < self.down_until

    def can_serve(self, tokens: int, now: float) -> bool:
        if now >= self.refill_at:
            self.remaining = float(self.tpm)
        return tokens <= self.remaining

    def consume(self, tokens: int) -> None:
        self.remaining = max(0.0, self.remaining - tokens)

    def update_from_headers(self, headers: dict[str, str], now: float) -> None:
        remaining = headers.get("x-ratelimit-remaining-tokens")
        if remaining is not None:
            try:
                self.remaining = float(remaining)
                self.refill_at = now + _parse_reset(headers.get("x-ratelimit-reset-tokens"))
            except ValueError:
                pass

    def exhaust(self, headers: dict[str, str], now: float) -> None:
        self.remaining = 0.0
        self.refill_at = now + _parse_reset(
            headers.get("x-ratelimit-reset-tokens") or headers.get("retry-after")
        )


def build_providers(settings: Settings) -> list[Provider]:
    keys = secrets()
    providers = []
    for entry in settings.llm_providers:
        spec, _, env = entry.partition("|")
        name, _, model = spec.partition("/")
        if name not in ENDPOINTS:
            continue
        key = keys.get(env) if env else None
        if env and not key:
            continue
        providers.append(Provider(name, model, env or None, key, DEFAULT_TPM[name]))
    return providers


class LLMRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http: HttpClient | None = None,
        providers: list[Provider] | None = None,
        recorder: Recorder | None = None,
        large_threshold: int = 6_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or get_settings()
        self.http = http or HttpClient(self.settings)
        self.providers = providers if providers is not None else build_providers(self.settings)
        self.recorder = recorder
        self.large_threshold = large_threshold
        self.clock = clock

    def _order(self, tokens: int) -> list[Provider]:
        large = tokens > self.large_threshold

        def rank(p: Provider) -> int:
            if p.name == "ollama":
                return 3  # local last resort
            if large:
                return 0 if p.name == "gemini" else 1
            return 0 if p.name == "groq" else 1

        return sorted(self.providers, key=rank)  # stable: config order within a rank

    async def generate(
        self,
        schema: type[T],
        messages: list[dict[str, str]],
        *,
        purpose: str,
        prompt_version: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4_000,
        max_wait_s: float = 60.0,
    ) -> tuple[T, CallInfo]:
        """Try providers in order; if all are only out of per-minute quota, wait for the
        earliest refill (up to `max_wait_s`) and try again instead of failing."""
        if not self.providers:
            raise LLMError("nenhum provedor de LLM configurado (veja .env / llm_providers)")
        need = estimate_tokens(messages) + max_tokens
        json_schema = {
            "name": schema.__name__,
            "strict": True,
            "schema": strict_json_schema(schema),
        }
        deadline = self.clock() + max_wait_s
        while True:
            errors: list[str] = []
            for provider in self._order(need):
                now = self.clock()
                if provider.is_down(now):
                    errors.append(f"{provider.name}/{provider.model}: indisponível (pausado)")
                    continue
                if not provider.can_serve(need, now):
                    errors.append(f"{provider.name}/{provider.key_label}: sem cota no minuto")
                    continue
                result = await self._call_with_repair(
                    provider,
                    schema,
                    messages,
                    json_schema,
                    purpose,
                    prompt_version,
                    temperature,
                    max_tokens,
                )
                if isinstance(result, tuple):
                    return result
                errors.append(result)
            waits = [
                p.refill_at
                for p in self.providers
                if not p.is_down(self.clock()) and p.refill_at > self.clock()
            ]
            if not waits or min(waits) > deadline:
                raise LLMError("todos os provedores falharam: " + " | ".join(errors))
            pause = max(0.5, min(waits) - self.clock())
            log.info("LLM: todos sem cota no minuto; aguardando %.0fs pela renovação", pause)
            await asyncio.sleep(pause)

    async def _call_with_repair(
        self,
        provider,
        schema,
        messages,
        json_schema,
        purpose,
        prompt_version,
        temperature,
        max_tokens,
    ):
        convo = list(messages)
        for attempt in (1, 2):  # 2nd attempt = repair round with the validation errors
            info = CallInfo(
                provider.name,
                provider.model,
                provider.key_label,
                purpose,
                prompt_version,
                repaired=attempt == 2,
            )
            body = {
                "model": provider.model,
                "messages": convo,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_schema", "json_schema": json_schema},
            }
            if provider.name in REASONING_PROVIDERS:
                # Reasoning tokens count against max_tokens: keep them low so the JSON fits
                # (a truncated JSON from gemini-2.5-flash was observed without this).
                body["reasoning_effort"] = "low"
            headers = {"Authorization": f"Bearer {provider.key}"} if provider.key else {}
            started = self.clock()
            response = await self.http.post_json(provider.url, body, headers=headers)
            info.latency_ms = int((self.clock() - started) * 1000)
            now = self.clock()

            if response.status == 429 or response.status == 0 or response.status >= 500:
                if response.status == 429:
                    provider.exhaust(response.headers, now)
                elif response.status == 0:
                    provider.down_until = now + DOWN_CONNECT_S  # e.g. local Ollama not running
                else:
                    provider.down_until = now + DOWN_5XX_S  # overloaded ("high demand")
                info.error = response.error or f"HTTP {response.status}"
                await self._record(info)
                return f"{provider.name}/{provider.key_label}: {info.error}"
            if not response.ok:
                info.error = f"HTTP {response.status}: {response.text()[:200]}"
                await self._record(info)
                return f"{provider.name}: {info.error}"

            provider.update_from_headers(response.headers, now)
            payload = response.json() or {}
            usage = payload.get("usage") or {}
            info.in_tokens, info.out_tokens = (
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
            provider.consume(int(usage.get("total_tokens") or 0))
            content = ((payload.get("choices") or [{}])[0].get("message") or {}).get(
                "content"
            ) or ""
            try:
                obj = schema.model_validate_json(_strip_fences(content))
            except (ValidationError, ValueError) as exc:
                info.error = f"saída inválida: {str(exc)[:300]}"
                await self._record(info)
                if attempt == 1:
                    convo = [
                        *messages,
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "A resposta não segue o schema/limites exigidos. Corrija e "
                                f"devolva apenas o JSON válido. Erros: {str(exc)[:1500]}"
                            ),
                        },
                    ]
                    continue
                return f"{provider.name}: {info.error}"
            info.ok = True
            await self._record(info)
            return obj, info
        return f"{provider.name}: reparo falhou"

    async def _record(self, info: CallInfo) -> None:
        if not info.ok:
            log.warning(
                "LLM %s/%s (%s) falhou: %s", info.provider, info.model, info.purpose, info.error
            )
        if self.recorder is not None:
            await self.recorder(info)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text


def db_recorder(db: Any) -> Recorder:
    async def record(info: CallInfo) -> None:
        await db.record_llm_call(info)

    return record


__all__ = [
    "CallInfo",
    "LLMError",
    "LLMRouter",
    "Provider",
    "build_providers",
    "db_recorder",
    "estimate_tokens",
]

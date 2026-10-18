import json
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, Field

from llm.prompts import load_prompt
from llm.router import LLMError, LLMRouter, Provider, _parse_reset
from llm.schema import strict_json_schema
from scraper.core.http import HttpClient


class Slide(BaseModel):
    papel: Literal["gancho", "corpo", "conclusao"]
    titulo: str = Field(max_length=60)


class Carousel(BaseModel):
    slides: list[Slide] = Field(min_length=2)
    legenda: str | None = None


GOOD = {
    "slides": [{"papel": "gancho", "titulo": "Selic cai"}, {"papel": "corpo", "titulo": "Por quê"}],
    "legenda": None,
}
BAD = {"slides": [{"papel": "gancho", "titulo": "x" * 80}]}  # too long + too few slides


def completion(obj, tokens=100, headers=None):
    body = {
        "choices": [{"message": {"content": json.dumps(obj)}}],
        "usage": {
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens // 2,
            "total_tokens": tokens,
        },
    }
    return httpx.Response(200, json=body, headers=headers or {})


def providers():
    return [
        Provider("groq", "gpt-oss", "GROQ_API_KEY", "k1", 8000),
        Provider("groq", "gpt-oss", "GROQ_API_KEY_2", "k2", 8000),
        Provider("gemini", "flash", "GEMINI_API_KEY", "k3", 250_000),
    ]


def router(settings, handler, provs=None, calls=None):
    recorded = calls if calls is not None else []

    async def recorder(info):
        recorded.append(info)

    http = HttpClient(settings, transport=httpx.MockTransport(handler))
    return LLMRouter(settings, http=http, providers=provs or providers(), recorder=recorder)


MSG = [{"role": "user", "content": "gere"}]


def test_strict_schema_is_closed_inlined_and_unconstrained():
    schema = strict_json_schema(Carousel)
    text = json.dumps(schema)
    assert "$defs" not in text and "$ref" not in text and "maxLength" not in text
    slide = schema["properties"]["slides"]["items"]
    assert slide["additionalProperties"] is False and slide["required"] == ["papel", "titulo"]
    assert schema["required"] == ["slides", "legenda"]  # optional fields still listed (nullable)


async def test_happy_path_uses_groq_first_and_records(settings):
    seen, calls = [], []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"]))
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        return completion(GOOD)

    r = router(settings, handler, calls=calls)
    obj, info = await r.generate(Carousel, MSG, purpose="write", prompt_version="w@1")
    assert obj.slides[0].titulo == "Selic cai"
    assert "groq.com" in seen[0][0] and seen[0][1] == "Bearer k1"
    assert info.ok and info.in_tokens == 50 and calls[-1].purpose == "write"


async def test_invalid_output_gets_one_repair_round(settings):
    replies = iter([completion(BAD), completion(GOOD)])
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["messages"])
        return next(replies)

    obj, info = await router(settings, handler).generate(Carousel, MSG, purpose="write")
    assert len(obj.slides) == 2 and info.repaired
    assert "Corrija" in sent[1][-1]["content"]  # validation errors fed back


async def test_429_fails_over_to_next_key_and_skips_exhausted_key(settings):
    hits = []

    def handler(request):
        key = request.headers["authorization"]
        hits.append(key)
        if key == "Bearer k1":
            return httpx.Response(429, headers={"x-ratelimit-reset-tokens": "30s"})
        return completion(GOOD)

    r = router(settings, handler)
    await r.generate(Carousel, MSG, purpose="write")
    await r.generate(Carousel, MSG, purpose="write")
    assert hits == ["Bearer k1", "Bearer k2", "Bearer k2"]  # k1 not retried within its reset


async def test_large_requests_go_to_gemini_first(settings):
    hits = []

    def handler(request):
        hits.append(str(request.url))
        return completion(GOOD)

    big = [{"role": "user", "content": "x" * 40_000}]
    await router(settings, handler).generate(Carousel, big, purpose="anchor")
    assert "generativelanguage.googleapis.com" in hits[0]


async def test_bucket_from_headers_skips_key_without_quota(settings):
    hits = []

    def handler(request):
        hits.append(request.headers["authorization"])
        return completion(
            GOOD, headers={"x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "40s"}
        )

    r = router(settings, handler)
    await r.generate(Carousel, MSG, purpose="write", max_tokens=2000)
    await r.generate(Carousel, MSG, purpose="write", max_tokens=2000)
    assert hits == ["Bearer k1", "Bearer k2"]


async def test_all_fail_raises_with_reasons(settings):
    r = router(settings, lambda request: httpx.Response(503))
    with pytest.raises(LLMError, match="todos os provedores falharam"):
        await r.generate(Carousel, MSG, purpose="write")


def test_reset_parsing():
    assert _parse_reset("22.11s") == pytest.approx(22.11)
    assert _parse_reset("1m26.4s") == pytest.approx(86.4)
    assert _parse_reset("120ms") == pytest.approx(0.12)


def test_prompt_versioning(tmp_path):
    (tmp_path / "p.md").write_text("Olá {{nome}}", encoding="utf-8")
    prompt = load_prompt("p", tmp_path)
    assert prompt.render(nome="Bruno") == "Olá Bruno" and prompt.version.startswith("p@")
    with pytest.raises(KeyError):
        prompt.render()


async def test_waits_for_quota_refill_instead_of_failing(settings):
    import llm.router as router_mod

    clock = {"t": 0.0}

    async def fake_sleep(seconds):
        clock["t"] += seconds

    hits = []

    def handler(request):
        hits.append(request.headers["authorization"])
        return completion(GOOD)

    provs = [Provider("groq", "gpt-oss", "GROQ_API_KEY", "k1", 8000)]
    provs[0].remaining, provs[0].refill_at = 0.0, 20.0  # exhausted for 20s
    r = router(settings, handler, provs)
    r.clock = lambda: clock["t"]
    original = router_mod.asyncio.sleep
    router_mod.asyncio.sleep = fake_sleep
    try:
        obj, _ = await r.generate(Carousel, MSG, purpose="write", max_wait_s=60)
    finally:
        router_mod.asyncio.sleep = original
    assert obj and hits == ["Bearer k1"] and clock["t"] >= 20


async def test_overloaded_provider_is_paused(settings):
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if "googleapis" in str(request.url):
            return httpx.Response(503)
        return completion(GOOD)

    # > large_threshold (→ gemini first) but still fits Groq's 8k tokens/min after the failover
    big = [{"role": "user", "content": "x" * 10_000}]
    r = router(settings, handler)
    await r.generate(Carousel, big, purpose="anchor")
    await r.generate(Carousel, big, purpose="anchor")
    gemini_hits = [h for h in hits if "googleapis" in h]
    assert len(gemini_hits) == 1  # paused after the 503, second call goes straight to groq


async def test_reasoning_effort_low_is_sent(settings):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return completion(GOOD)

    await router(settings, handler).generate(Carousel, MSG, purpose="write")
    assert bodies[0]["reasoning_effort"] == "low"

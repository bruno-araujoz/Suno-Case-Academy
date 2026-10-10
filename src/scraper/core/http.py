"""Shared async HTTP client: HTTP/2, per-host rate limit, conditional GET, retries.

`HttpClient.get` never raises on network problems: it always returns a `FetchResult`
(status 0 = transport failure). One broken source must never take down the others, and the
self-healing layer needs the status code (404, 403, 304...) to decide what to do.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from aiolimiter import AsyncLimiter

from .config import Settings, get_settings
from .logging import get_logger

log = get_logger("http")

_RETRY_STATUS = {429, 500, 502, 503, 504}
_CHARSET_RE = re.compile(r"charset=([\w-]+)", re.IGNORECASE)


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    @property
    def etag(self) -> str | None:
        return self.headers.get("etag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("last-modified")

    @property
    def is_pdf(self) -> bool:
        # Content-Type lies (CVM serves PDFs as text/html): trust the magic bytes.
        return self.content[:5] == b"%PDF-"

    def text(self) -> str:
        match = _CHARSET_RE.search(self.headers.get("content-type", ""))
        encoding = match.group(1) if match else "utf-8"
        try:
            return self.content.decode(encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any | None:
        try:
            return json.loads(self.content)
        except (ValueError, UnicodeDecodeError):
            return None


class HttpClient:
    """One pooled client for the whole run; rate limits are applied per host."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.AsyncClient(
            http2=transport is None,
            transport=transport,
            timeout=httpx.Timeout(self.settings.request_timeout, connect=10.0),
            follow_redirects=True,
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            },
            limits=httpx.Limits(
                max_connections=self.settings.max_connections,
                max_keepalive_connections=self.settings.max_connections // 2,
            ),
        )
        self._limiters: dict[str, AsyncLimiter] = {}

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _limiter(self, url: str) -> AsyncLimiter:
        host = urlsplit(url).netloc.lower()
        if host not in self._limiters:
            rps = self.settings.per_host_rps_overrides.get(host, self.settings.per_host_rps)
            self._limiters[host] = AsyncLimiter(rps, 1.0)
        return self._limiters[host]

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("retry-after") if response is not None else None
        if retry_after:
            try:
                wait = float(retry_after)
            except ValueError:
                try:
                    wait = parsedate_to_datetime(retry_after).timestamp() - time.time()
                except (TypeError, ValueError):
                    wait = 0.0
            if wait > 0:
                return min(wait, self.settings.retry_after_cap)
        base = self.settings.retry_backoff * (2**attempt)
        return base + random.uniform(0, base / 2)

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        req_headers = dict(headers or {})
        if etag:
            req_headers["If-None-Match"] = etag
        if last_modified:
            req_headers["If-Modified-Since"] = last_modified

        attempts = max(1, self.settings.http_retries)
        error: str | None = None
        status = 0
        for attempt in range(attempts):
            start = time.perf_counter()
            response: httpx.Response | None = None
            try:
                async with self._limiter(url):
                    response = await self._client.get(url, params=params, headers=req_headers)
            except httpx.HTTPError as exc:
                status = 0
                error = f"{type(exc).__name__}: {exc}"
            else:
                status = response.status_code
                if status not in _RETRY_STATUS or attempt == attempts - 1:
                    return FetchResult(
                        url=str(response.url),
                        status=status,
                        content=response.content,
                        headers={k.lower(): v for k, v in response.headers.items()},
                        error=None if status < 400 else f"HTTP {status}",
                        elapsed_ms=(time.perf_counter() - start) * 1000,
                    )
                error = f"HTTP {status}"
            if attempt < attempts - 1:
                await asyncio.sleep(self._backoff(attempt, response))

        log.warning("GET %s falhou após %d tentativas: %s", url, attempts, error)
        return FetchResult(url=url, status=status, error=error)

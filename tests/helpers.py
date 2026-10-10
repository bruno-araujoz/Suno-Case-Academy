"""Test helpers: route HTTP requests to recorded fixtures (no network)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import httpx

from scraper.core.config import Settings
from scraper.core.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures"
Route = str | Path | tuple[int, bytes] | Callable[[httpx.Request], httpx.Response]


def fixture_client(settings: Settings, routes: dict[str, Route]) -> tuple[HttpClient, list[str]]:
    """HttpClient whose requests are answered by the first regex in `routes` matching the URL.

    Route values: fixture path relative to tests/fixtures, (status, body) or a callable.
    Unmatched URLs return 404. Returns the client and the list of requested URLs.
    """
    calls: list[str] = []
    compiled = [(re.compile(pattern), target) for pattern, target in routes.items()]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        for pattern, target in compiled:
            if pattern.search(url):
                if callable(target):
                    return target(request)
                if isinstance(target, tuple):
                    return httpx.Response(target[0], content=target[1])
                return httpx.Response(200, content=(FIXTURES / target).read_bytes())
        return httpx.Response(404)

    return HttpClient(settings, transport=httpx.MockTransport(handler)), calls

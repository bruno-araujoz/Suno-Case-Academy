import httpx

from scraper.core.http import HttpClient


def client(settings, handler) -> HttpClient:
    return HttpClient(settings, transport=httpx.MockTransport(handler))


async def test_conditional_get_sends_validators_and_reports_304(settings):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304)

    async with client(settings, handler) as http:
        result = await http.get(
            "https://x.test/feed", etag='"abc"', last_modified="Mon, 01 Jan 2026"
        )
    assert result.not_modified and not result.ok
    assert seen["if-none-match"] == '"abc"'
    assert seen["if-modified-since"] == "Mon, 01 Jan 2026"


async def test_retries_on_503_then_succeeds(settings):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    async with client(settings, handler) as http:
        result = await http.get("https://x.test/api")
    assert calls["n"] == 3
    assert result.ok and result.json() == {"ok": True}


async def test_never_raises_on_transport_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with client(settings, handler) as http:
        result = await http.get("https://down.test/")
    assert result.status == 0 and not result.ok
    assert "ConnectError" in (result.error or "")


async def test_404_is_returned_not_retried(settings):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    async with client(settings, handler) as http:
        result = await http.get("https://x.test/gone")
    assert calls["n"] == 1 and result.status == 404 and result.error == "HTTP 404"


async def test_pdf_detected_by_magic_bytes_not_content_type(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.7 ...", headers={"Content-Type": "text/html"})

    async with client(settings, handler) as http:
        result = await http.get("https://cvm.test/doc")
    assert result.is_pdf


async def test_charset_from_content_type(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="ação".encode("latin-1"),
            headers={"Content-Type": "text/csv; charset=latin-1"},
        )

    async with client(settings, handler) as http:
        result = await http.get("https://x.test/csv")
    assert result.text() == "ação"

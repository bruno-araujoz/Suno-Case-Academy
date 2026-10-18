"""CSS extraction schemas for HTML listings (self-healing L4).

Same format as Crawl4AI's `JsonCssExtractionStrategy` ({name, baseSelector, fields[]}), so an
LLM-generated schema can be used directly; applying it is done here with selectolax (fast, no
browser). Schemas are versioned files: schemas/<source>.v<N>.json — never overwritten.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from ..core.config import Settings
from ..core.logging import get_logger

log = get_logger("heal.schema")

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "schemas"
_VERSION = re.compile(r"\.v(\d+)\.json$")

Schema = dict[str, Any]
SchemaGenerator = Callable[[str, str], Awaitable[Schema | None]]  # (html, url) -> schema

QUERY = (
    "This is a news listing page of a Brazilian financial news site. Extract every news item "
    "in the main list: fields 'title' (headline text), 'url' (attribute href of the headline "
    "link) and 'date' (publication date/time text or datetime attribute, if present). Use "
    "stable selectors (semantic tags, href patterns, data-* attributes); avoid nth-child and "
    "auto-generated class names."
)


# ------------------------------------------------------------------ apply / validate


def apply_schema(html: str, schema: Schema, base_url: str) -> list[dict[str, str | None]]:
    tree = LexborHTMLParser(html)
    items: list[dict[str, str | None]] = []
    for node in tree.css(schema["baseSelector"]):
        item: dict[str, str | None] = {}
        for field in schema.get("fields", []):
            target = node.css_first(field["selector"]) if field.get("selector") else node
            value: str | None = None
            if target is not None:
                kind = field.get("type", "text")
                if kind == "attribute":
                    value = target.attributes.get(field.get("attribute", "href"))
                elif kind == "html":
                    value = target.html
                else:
                    value = target.text(strip=True)
            item[field["name"]] = value or field.get("default")
        if item.get("url"):
            item["url"] = urljoin(base_url, str(item["url"]))
        items.append(item)
    return items


def listing_is_healthy(
    items: list[dict[str, str | None]], base_url: str, min_items: int = 5
) -> bool:
    """Contract for a listing: enough items, real headlines, links on the site's domain."""
    host = urlsplit(base_url).netloc.removeprefix("www.")
    good = [
        i
        for i in items
        if len((i.get("title") or "").strip()) >= 15
        and (url := i.get("url"))
        and urlsplit(url).netloc.removeprefix("www.").endswith(host)
    ]
    return len(good) >= min_items and len(good) / max(1, len(items)) >= 0.7


# ------------------------------------------------------------------ versioned storage


def schema_path(source: str, version: int) -> Path:
    return SCHEMA_DIR / f"{source}.v{version}.json"


def load_schema(source: str, version: int) -> Schema | None:
    path = schema_path(source, version)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def next_version(source: str) -> int:
    versions = [
        int(m.group(1))
        for p in SCHEMA_DIR.glob(f"{source}.v*.json")
        if (m := _VERSION.search(p.name))
    ]
    return max(versions, default=0) + 1


def save_schema(source: str, schema: Schema) -> int:
    SCHEMA_DIR.mkdir(exist_ok=True)
    version = next_version(source)
    schema_path(source, version).write_text(
        json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return version


# ------------------------------------------------------------------ LLM generator (Crawl4AI)


_KEEP_ATTRS = {"class", "id", "href", "datetime"}
_SPACES = re.compile(r">\s+<")


def _clean_html(html: str, limit: int = 15_000) -> str:
    """Shrink a listing page to what a selector-writing LLM needs (~4k tokens).

    Free LLM tiers cap requests (Groq: 8k tokens/min), and the raw page is 25k+ tokens. Page
    chrome, scripts, media and non-structural attributes go; the main content area is kept.
    """
    tree = LexborHTMLParser(html)
    for node in tree.css(
        "script, style, noscript, svg, iframe, head, nav, header, footer, "
        "aside, form, img, picture, source, video, figure, button, input"
    ):
        node.decompose()
    for node in tree.css("*"):
        for attr in [a for a in node.attributes if a not in _KEEP_ATTRS]:
            del node.attrs[attr]
    root = tree.css_first("main") or tree.body or tree.root
    markup = _SPACES.sub("><", root.html or "") if root is not None else ""
    return markup[:limit]


def _secrets() -> dict[str, str]:
    from ..core.secrets import secrets

    return secrets()


def llm_providers(settings: Settings) -> list[tuple[str, str | None]]:
    """[(litellm provider string, api token)] in fallback order; skips providers without key."""
    secrets = _secrets()
    out: list[tuple[str, str | None]] = []
    for entry in settings.llm_providers:
        provider, _, env = entry.partition("|")
        token = secrets.get(env) if env else None
        if env and not token:
            continue
        out.append((provider, token))
    return out


def crawl4ai_generator(settings: Settings) -> SchemaGenerator | None:
    """Schema generator backed by Crawl4AI + the LLM fallback chain; None if unavailable."""
    try:
        from crawl4ai import JsonCssExtractionStrategy, LLMConfig
    except ImportError:
        return None
    providers = llm_providers(settings)
    if not providers:
        return None

    async def generate(html: str, url: str) -> Schema | None:
        cleaned = _clean_html(html)
        for provider, token in providers:
            config = LLMConfig(provider=provider, api_token=token)
            try:
                agen = getattr(JsonCssExtractionStrategy, "agenerate_schema", None)
                kwargs = dict(html=cleaned, query=QUERY, schema_type="CSS", llm_config=config)
                if agen is not None:
                    schema = await agen(**kwargs)
                else:
                    schema = await asyncio.to_thread(
                        JsonCssExtractionStrategy.generate_schema, **kwargs
                    )
                if isinstance(schema, str):
                    schema = json.loads(schema)
                if isinstance(schema, dict) and schema.get("baseSelector"):
                    log.info("Schema gerado via %s para %s", provider, url)
                    return schema
            except Exception as exc:  # provider down/rate limited/invalid JSON: next one
                log.warning("generate_schema falhou com %s: %s", provider, exc)
        return None

    return generate

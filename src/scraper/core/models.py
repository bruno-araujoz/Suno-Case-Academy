"""Document contract and normalization helpers.

Everything a source produces becomes a `Document`. Validation happens here, at the boundary:
an item that fails the contract is dropped and counted in `source_health` (self-healing L0).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import xxhash
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from selectolax.lexbor import LexborHTMLParser

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MIN_DATE = datetime(2000, 1, 1, tzinfo=UTC)

DocType = Literal[
    "copom_ata", "copom_comunicado", "fato_relevante", "press_release", "ibge_release", "news"
]
Tier = Literal["official", "news", "coverage"]
ExtractionLevel = Literal["api", "feed", "pdf", "article", "browser", "none"]
Status = Literal["ready", "pending_enrich", "failed"]

_TRACKING_PARAM = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|cmpid|origin)$", re.I)
_BR_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$")
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t ]+")


# --------------------------------------------------------------------------- helpers


def first(item: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    """First non-empty value among candidate keys (tolerates schema drift between endpoints)."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, dict):  # e.g. WordPress {"rendered": "..."}
            value = value.get("rendered") or value.get("name") or value.get("value")
        if value not in (None, "", [], {}):
            return value.strip() if isinstance(value, str) else value
    return None


def iter_items(
    payload: Any, keys: tuple[str, ...] = ("conteudo", "data", "results", "items", "value")
) -> list[dict[str, Any]]:
    """Find the list of records inside common API envelopes."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):  # single record envelope
                return [value]
    return []


def canonical_url(url: str) -> str:
    """https, lowercase host, no fragment/tracking params, sorted query, no trailing slash."""
    raw = url.strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"URL inválida: {url!r}")
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAM.match(k)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO, RFC 2822, dd/mm/yyyy, date or datetime. Naive values are São Paulo time."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip()
        match = _BR_DATE.match(text)
        if match:
            day, month, year, hour, minute, second = (int(g) if g else 0 for g in match.groups())
            dt = datetime(year, month, day, hour, minute, second)
        else:
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(text)
                except (TypeError, ValueError):
                    return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SAO_PAULO)
    return dt.astimezone(UTC)


def html_to_text(html: str | None) -> str:
    """Fast HTML → plain text (selectolax), one block per line, scripts/styles removed."""
    if not html:
        return ""
    tree = LexborHTMLParser(html)
    for node in tree.css("script, style, noscript, iframe, svg, form"):
        node.decompose()
    root = tree.body or tree.root
    if root is None:
        return ""
    text = root.text(separator="\n", strip=True)
    text = _MULTI_SPACE.sub(" ", text)
    return _MULTI_NL.sub("\n\n", text).strip()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# --------------------------------------------------------------------------- contract


class Document(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    source: str
    doc_type: DocType
    tier: Tier
    url: str
    title: str = Field(min_length=3, max_length=1000)
    published_at: datetime
    author: str | None = None
    content_text: str | None = None
    pdf_url: str | None = None
    extraction_level: ExtractionLevel = "none"
    status: Status = "ready"
    relevance_score: float | None = None
    cluster_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url", "pdf_url", mode="before")
    @classmethod
    def _canonical(cls, value: Any) -> Any:
        return canonical_url(str(value)) if value else value

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: Any) -> Any:
        return html_to_text(value) if isinstance(value, str) and "<" in value else value

    @field_validator("published_at", mode="before")
    @classmethod
    def _parse_date(cls, value: Any) -> datetime:
        dt = parse_datetime(value)
        if dt is None:
            raise ValueError(f"data inválida: {value!r}")
        if dt < MIN_DATE or dt > datetime.now(UTC) + timedelta(days=1):
            raise ValueError(f"data implausível: {dt.isoformat()}")
        return dt

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url_hash(self) -> str:
        return xxhash.xxh3_64_hexdigest(self.url)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str | None:
        if not self.content_text:
            return None
        return xxhash.xxh3_64_hexdigest(normalize_text(self.content_text))

    def needs_enrichment(self, min_chars: int) -> bool:
        if self.meta.get("no_enrich") or self.extraction_level == "pdf":
            return False
        if self.meta.get("teaser") and self.extraction_level == "feed":
            return True  # feed carries only a lead ("Leia mais em: ..."), whatever its length
        return len(self.content_text or "") < min_chars

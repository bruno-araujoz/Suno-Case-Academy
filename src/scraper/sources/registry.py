"""Load sources.yaml into typed configs."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "sources.yaml"


class FeedConfig(BaseModel):
    name: str
    kind: Literal["rss", "wpjson", "html", "google_news"]  # html = listagem + schema CSS
    url: str | None = None
    homepage: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    queries: list[str] = Field(default_factory=list)
    window: str = "3d"  # Google News `when:` operator
    ttl: str | None = None  # overrides defaults.feed_ttl / defaults.coverage_ttl
    searchable: bool = False  # WordPress search (?search=) used for on-demand topic search
    enabled: bool = True


_DURATION = re.compile(r"^(\d+)([mhd])$")


def parse_duration(text: str) -> timedelta:
    match = _DURATION.match(text.strip())
    if not match:
        raise ValueError(f"duração inválida: {text!r} (use 15m, 1h, 2d)")
    value, unit = int(match.group(1)), match.group(2)
    return {"m": timedelta(minutes=value), "h": timedelta(hours=value), "d": timedelta(days=value)}[
        unit
    ]


class Registry(BaseModel):
    defaults: dict[str, str] = Field(default_factory=dict)
    official: dict[str, dict[str, Any]] = Field(default_factory=dict)
    feeds: list[FeedConfig] = Field(default_factory=list)
    coverage: list[FeedConfig] = Field(default_factory=list)

    def official_enabled(self, name: str) -> bool:
        return bool(self.official.get(name, {}).get("enabled", False))

    def ttls(self) -> dict[str, timedelta]:
        """Freshness window of every enabled source (on-demand collection)."""
        feed_ttl = self.defaults.get("feed_ttl", "15m")
        cov_ttl = self.defaults.get("coverage_ttl", "1h")
        out = {
            name: parse_duration(cfg.get("ttl", "24h"))
            for name, cfg in self.official.items()
            if cfg.get("enabled")
        }
        out |= {f.name: parse_duration(f.ttl or feed_ttl) for f in self.feeds if f.enabled}
        out |= {c.name: parse_duration(c.ttl or cov_ttl) for c in self.coverage if c.enabled}
        return out


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    return Registry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

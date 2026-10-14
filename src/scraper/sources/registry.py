"""Load sources.yaml into typed configs."""

from __future__ import annotations

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
    enabled: bool = True


class Registry(BaseModel):
    official: dict[str, dict[str, Any]] = Field(default_factory=dict)
    feeds: list[FeedConfig] = Field(default_factory=list)
    coverage: list[FeedConfig] = Field(default_factory=list)

    def official_enabled(self, name: str) -> bool:
        return bool(self.official.get(name, {}).get("enabled", False))


def load_registry(path: Path = REGISTRY_PATH) -> Registry:
    return Registry.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

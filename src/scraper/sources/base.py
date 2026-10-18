"""Source contract: every source yields validated `Document`s and fills a `SourceReport`."""

from __future__ import annotations

import abc
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from ..core.config import Settings, get_settings
from ..core.db import SourceState
from ..core.http import FetchResult, HttpClient
from ..core.logging import get_logger
from ..core.models import Document


class StateStore(Protocol):
    async def get_state(self, source: str, endpoint_key: str) -> SourceState | None: ...
    async def save_state(self, state: SourceState) -> None: ...
    async def get_heal_after(self, source: str) -> datetime | None: ...
    async def set_heal_after(self, source: str, until: datetime | None) -> None: ...


class MemoryStateStore:
    """State store for dry-runs and tests (nothing persisted)."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], SourceState] = {}
        self._heal_after: dict[str, datetime | None] = {}

    async def get_state(self, source: str, endpoint_key: str) -> SourceState | None:
        return self._data.get((source, endpoint_key))

    async def save_state(self, state: SourceState) -> None:
        self._data[(state.source, state.endpoint_key)] = state

    async def get_heal_after(self, source: str) -> datetime | None:
        return self._heal_after.get(source)

    async def set_heal_after(self, source: str, until: datetime | None) -> None:
        self._heal_after[source] = until


@dataclass
class SourceReport:
    source: str
    status: str = "ok"  # ok | not_modified | degraded | healed | failed
    level: str | None = None
    items_seen: int = 0  # raw entries read from the source (health signal, incl. already known)
    items_valid: int = 0  # new entries that passed the contract
    items_invalid: int = 0  # new entries rejected by the contract
    items_new: int = 0
    http_status: int | None = None
    error: str | None = None
    duration_ms: int = 0
    newest_entry_at: datetime | None = None  # freshest entry in the payload (stale detection)
    invalid_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceContext:
    http: HttpClient
    state: StateStore
    since: datetime
    known: set[str] = field(default_factory=set)  # url_hash already stored (skip detail fetches)
    settings: Settings = field(default_factory=get_settings)


class Source(abc.ABC):
    """Base class. Subclasses implement `_collect`; `collect` adds timing and error isolation."""

    name: str = "base"

    def __init__(self, ctx: SourceContext) -> None:
        self.ctx = ctx
        self.report = SourceReport(source=self.name)
        self.log = get_logger(f"source.{self.name}")

    @abc.abstractmethod
    def _collect(self) -> AsyncIterator[Document]: ...

    async def collect(self) -> AsyncIterator[Document]:
        start = time.perf_counter()
        try:
            async for doc in self._collect():
                yield doc
        except Exception as exc:  # isolation: a bug in one source never stops the run
            self.log.exception("Fonte %s falhou", self.name)
            self.report.status = "failed"
            self.report.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.report.duration_ms = int((time.perf_counter() - start) * 1000)

    # ------------------------------------------------------------------ helpers

    def build(self, **fields: Any) -> Document | None:
        """Validate one item against the contract; count instead of raising."""
        try:
            doc = Document(source=self.name, **fields)
        except ValidationError as exc:
            self.report.items_invalid += 1
            if len(self.report.invalid_samples) < 3:
                self.report.invalid_samples.append(str(exc.errors()[0].get("msg")))
            return None
        self.report.items_valid += 1
        return doc

    def is_known(self, url: str) -> bool:
        try:
            probe = Document(
                source=self.name,
                doc_type="news",
                tier="news",
                url=url,
                title="probe",
                published_at=self.ctx.since,
            )
        except ValidationError:
            return False
        return probe.url_hash in self.ctx.known

    def fail(self, result: FetchResult, what: str) -> None:
        self.report.status = "failed"
        self.report.http_status = result.status
        self.report.error = f"{what}: {result.error or result.status}"
        self.log.warning("%s: %s", self.name, self.report.error)

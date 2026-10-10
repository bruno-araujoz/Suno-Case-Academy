"""Process pool for CPU-bound extraction (PDF, trafilatura) so the event loop never blocks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from typing import TypeVar

T = TypeVar("T")


class CpuPool:
    def __init__(self, workers: int) -> None:
        self._executor = ProcessPoolExecutor(max_workers=max(1, workers)) if workers > 0 else None

    async def run(self, fn: Callable[..., T], *args: object) -> T:
        if self._executor is None:  # workers=0: inline (tests, debugging)
            return fn(*args)
        return await asyncio.get_running_loop().run_in_executor(self._executor, fn, *args)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

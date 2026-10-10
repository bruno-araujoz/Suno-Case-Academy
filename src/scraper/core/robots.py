"""robots.txt check (cached per host) for page fetches: articles, homepages, HTML listings.

Feeds and documented APIs are published for automated consumption and are not checked.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .http import HttpClient


class RobotsCache:
    def __init__(self, http: HttpClient) -> None:
        self.http = http
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._parsers:
            result = await self.http.get(f"{root}/robots.txt")
            if result.ok:
                parser = RobotFileParser()
                parser.parse(result.text().splitlines())
                self._parsers[root] = parser
            else:  # missing/unreachable robots.txt: crawling allowed
                self._parsers[root] = None
        parser = self._parsers[root]
        return True if parser is None else parser.can_fetch("*", url)

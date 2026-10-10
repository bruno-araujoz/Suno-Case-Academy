"""PDF → text with PyMuPDF (fastest option in our benchmark: 28 pages in ~50 ms)."""

from __future__ import annotations

import re

_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_WS = re.compile(r"\s+")

MAX_PAGES = 80  # releases/fatos relevantes are short; guards against huge attachments


def pdf_to_text(data: bytes) -> str:
    """One paragraph per PDF text block; lines inside a block are joined."""
    import pymupdf  # imported inside the worker process

    paragraphs: list[str] = []
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        for page in pdf.pages(0, min(len(pdf), MAX_PAGES)):
            # blocks: (x0, y0, x1, y1, text, block_no, block_type); type 0 = text
            for block in page.get_text("blocks", sort=True):
                if block[6] != 0:
                    continue
                text = _WS.sub(" ", _HYPHEN_BREAK.sub(r"\1\2", block[4])).strip()
                if text:
                    paragraphs.append(text)
    return "\n\n".join(paragraphs)

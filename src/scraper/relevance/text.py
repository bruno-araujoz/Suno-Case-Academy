"""Text normalization shared by clustering and lexical scoring."""

from __future__ import annotations

import re
import unicodedata

_WORD = re.compile(r"[a-z0-9][a-z0-9\-]*")
_TICKER = re.compile(r"\b[A-Z]{4}\d{1,2}\b")
_NUMBER = re.compile(r"(?<![A-Za-z\d])(?:\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)")
_YEAR = re.compile(r"^(19|20)\d{2}$")

STOPWORDS = frozenset(
    """
a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem sob sobre
ao aos e ou mas que se seu sua seus suas ele ela eles elas isso esse essa este esta como mais
menos muito ja ate apos entre ser sao foi era tem ter vai vao pode deve diz dizem segundo
veja entenda saiba confira hoje ontem amanha nesta neste nessa nesse apos durante quando onde
qual quais quem porque pois tambem ainda so sim nao
""".split()
)


def fold(text: str) -> str:
    """Lowercase without accents."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def numbers(text: str) -> set[str]:
    """Figures like '0,82%' or 'R$ 1,5 bi' are the strongest event signal in a headline."""
    out = set()
    for raw in _NUMBER.findall(text):
        value = raw.replace(".", "").replace(",", ".") if "," in raw else raw
        if len(value.replace(".", "")) >= 2 and not _YEAR.match(value):
            out.add(f"#{value}")
    return out


def tokens(text: str) -> set[str]:
    """Content tokens for similarity: folded words (len>=3, no stopwords), tickers, figures."""
    words = {
        w
        for w in _WORD.findall(fold(text))
        if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()  # figures come from numbers()
    }
    return words | {t.lower() for t in _TICKER.findall(text)} | numbers(text)


def tickers(text: str) -> set[str]:
    return set(_TICKER.findall(text))

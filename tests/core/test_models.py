from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scraper.core.models import (
    Document,
    canonical_url,
    first,
    html_to_text,
    iter_items,
    parse_datetime,
)


def doc(**over):
    base = dict(
        source="s",
        doc_type="news",
        tier="news",
        url="https://a.com/x",
        title="Título válido",
        published_at="2026-09-22",
    )
    return Document(**(base | over))


def test_canonical_url_strips_tracking_and_normalizes():
    url = "http://WWW.Site.com/noticia/?utm_source=x&b=2&a=1&fbclid=z#topo"
    assert canonical_url(url) == "https://www.site.com/noticia?a=1&b=2"


def test_same_url_variants_share_hash():
    assert doc(url="https://a.com/x/?utm_medium=rss").url_hash == doc(url="http://A.com/x").url_hash


def test_naive_dates_are_sao_paulo_and_stored_utc():
    dt = parse_datetime("2026-09-22T10:00:00")
    assert dt == datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    assert parse_datetime("22/09/2026") == datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    assert parse_datetime("Fri, 09 Oct 2026 23:08:20 GMT").tzinfo is not None


@pytest.mark.parametrize(
    "bad", ["1999-12-31", (datetime.now(UTC) + timedelta(days=5)).isoformat(), "ontem"]
)
def test_implausible_or_invalid_dates_fail_contract(bad):
    with pytest.raises(ValidationError):
        doc(published_at=bad)


def test_first_tolerates_key_drift_and_wordpress_rendered():
    assert first({"nro_reuniao": 281}, ("nroReuniao", "nro_reuniao")) == 281
    assert first({"title": {"rendered": " Selic "}}, ("title",)) == "Selic"
    assert first({"a": ""}, ("a", "b")) is None


def test_iter_items_finds_bcb_envelope():
    assert iter_items({"conteudo": [{"x": 1}, "lixo"]}) == [{"x": 1}]
    assert iter_items({"conteudo": {"x": 1}}) == [{"x": 1}]


def test_html_to_text_drops_scripts_and_keeps_blocks():
    text = html_to_text(
        "<div><h3>A) Conjuntura</h3><script>x()</script><p>Selic em 13,75%.</p></div>"
    )
    assert text == "A) Conjuntura\nSelic em 13,75%."


def test_content_hash_ignores_whitespace_and_case():
    assert (
        doc(content_text="Selic  sobe").content_hash
        == doc(content_text="selic sobe\n").content_hash
    )

from datetime import UTC, datetime, timedelta

import pytest

from scraper.core.models import Document
from scraper.relevance.cluster import Clusterer, Item
from scraper.relevance.scorer import coverage_score, lexical_score, recency_score, score
from scraper.relevance.stage import RelevanceStage
from scraper.relevance.text import numbers, tokens
from scraper.sources.coverage import google_news, publisher_key
from scraper.sources.registry import FeedConfig
from tests.helpers import fixture_client

T0 = datetime(2026, 10, 9, 12, tzinfo=UTC)


def item(key, title, pub, hours=0):
    return Item(key, title, pub, T0 + timedelta(hours=hours))


def test_tokens_keep_figures_and_tickers_but_not_years_or_stopwords():
    toks = tokens("Santander (SANB11) pagará R$ 1,5 bilhão em JCP; IPCA sobe 0,82% em 2026")
    assert {"sanb11", "#1.5", "#0.82", "ipca", "santander"} <= toks
    assert "#2026" not in toks and "2026" not in toks and "#11" not in toks and "em" not in toks
    assert numbers("0,82% e 1.234,5") == {"#0.82", "#1234.5"}


def test_same_event_different_wording_clusters_together():
    c = Clusterer()
    a = c.add(item("a", "IPCA: inflação sobe 0,82% em setembro, acima do esperado", "infomoney"))
    b = c.add(item("b", "IPCA sobe 0,82% em setembro, pressionado por energia", "cnn", 1))
    d = c.add(item("d", "Inflação sobe 0,82% em setembro, diz IBGE", "agencia", 2))
    assert a == b == d


def test_related_but_different_events_do_not_chain():
    c = Clusterer()
    ipca = c.add(item("a", "IPCA sobe 0,82% em setembro e juros futuros sobem", "x"))
    bolsa = c.add(
        item("b", "Ibovespa renova recorde aos 209 mil pontos; juros futuros caem", "y", 1)
    )
    santander = c.add(item("c", "Santander (SANB11) aprova R$ 1,5 bi em proventos", "z", 2))
    assert len({ipca, bolsa, santander}) == 3


def test_shared_ticker_lowers_the_bar_and_time_gap_splits():
    c = Clusterer()
    a = c.add(item("a", "Pão de Açúcar (PCAR3): Justiça homologa plano", "moneytimes"))
    b = c.add(
        item("b", "GPA (PCAR3) tem recuperação extrajudicial homologada pela Justiça", "valor", 3)
    )
    late = c.add(item("c", "Pão de Açúcar (PCAR3): Justiça homologa plano", "outro", 24 * 5))
    assert a == b and late != a


def test_lexical_title_counts_double_and_saturates():
    strong = lexical_score("Copom corta a Selic e ata do Copom sinaliza forward guidance", None)
    body_only = lexical_score("Notícia", "O Copom decidiu cortar a Selic.")
    none = lexical_score("Receita de bolo de cenoura", "Misture farinha e ovos.")
    assert 0 < none < body_only < strong < 1 or none == 0
    assert none == 0 and strong > 0.9


def test_score_components():
    assert coverage_score(1) == 0 and coverage_score(5) == 1 and coverage_score(9) == 1
    assert recency_score(T0, 48, now=T0 + timedelta(hours=48)) == pytest.approx(0.5)

    class S:
        relevance_weights = (0.35, 0.25, 0.25, 0.15)
        relevance_half_life_hours = 48.0

    official = score(S, lexical=0.9, tier="official", publishers=5, published_at=T0, now=T0)
    lone_news = score(S, lexical=0.2, tier="news", publishers=1, published_at=T0, now=T0)
    assert official.score > 0.9 > lone_news.score


def test_publisher_aliases():
    assert publisher_key("Valor Econômico") == publisher_key("valor") == "valor"
    assert publisher_key("Estadão") == publisher_key("estadao_economia")


async def test_google_news_coverage_parses_publisher_suffix(settings):
    http, calls = fixture_client(settings, {r"news\.google\.com": "coverage/google_news_ipca.xml"})
    cfg = FeedConfig(name="google_news", kind="google_news", queries=["IPCA", "Selic"])
    async with http:
        signals, report = await google_news(http, cfg)
    assert len(calls) == 2 and report["status"] == "ok"
    assert signals and all(s.publisher and " - " not in s.title[-3:] for s in signals)
    assert len({s.url_hash for s in signals}) == len(signals)  # deduped across queries


async def test_stage_counts_outlets_including_coverage(settings):
    def doc(src, title, h):
        return Document(
            source=src,
            doc_type="news",
            tier="news",
            url=f"https://{src}.com/{h}",
            title=title,
            published_at=datetime.now(UTC) - timedelta(hours=h),
            content_text="O IPCA subiu 0,82% em setembro, informou o IBGE.",
        )

    stage = RelevanceStage(settings)
    stage.observe(
        [
            doc("infomoney", "IPCA sobe 0,82% em setembro, acima do esperado", 3),
            doc("valor", "IPCA de setembro sobe 0,82%, mostra IBGE", 2),
            doc("suno", "Receita de bolo", 1),
        ]
    )
    stats = await stage.finalize(db=None, coverage=[], write=False)
    assert stats.scored == 3 and stats.clusters_multi_publisher == 1
    best = stats.top[0]
    assert best[1] == 2 and "IPCA" in best[3]

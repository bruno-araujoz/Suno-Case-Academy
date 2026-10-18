import pytest

from evals.evaluator import evaluate, level_targets
from evals.grounding import ground
from evals.jargon import analyze
from evals.readability import readability, syllables
from generation.schemas import Anchors, Carousel, Fact, Script, ScriptBlock, Slide
from glossary.matcher import Glossary, Term

G = Glossary(
    [
        Term("Selic", "intermediario"),
        Term("hiato do produto", "avancado"),
        Term("expectativas desancoradas", "avancado"),
        Term("inflação", "basico"),
    ]
)

ATA = (
    "A desancoragem das expectativas de inflação, a resiliência da atividade econômica e a "
    "elevação das projeções de inflação requerem uma política monetária significativamente "
    "contracionista por período bastante prolongado, com vistas a assegurar a convergência da "
    "inflação à meta no horizonte relevante, considerando o hiato do produto positivo."
)
SIMPLE = (
    "O Banco Central baixou os juros. Isso deixa o crédito mais barato. Comprar a prazo "
    "fica mais fácil. Mas os preços ainda sobem. Por isso o banco vai com calma. Ele quer "
    "ver a inflação cair mais. Assim o seu dinheiro vale mais no fim do mês."
)

ANCHORS = Anchors(
    evento="Copom reduz a Selic para 13,75%",
    contexto="Primeiro corte do ciclo.",
    fatos=[
        Fact(
            id="F1",
            afirmacao="O Copom reduziu a Selic para 13,75% ao ano",
            numeros=["13,75%"],
            doc_id="D1",
            citacao="reduziu a taxa Selic para 13,75% a.a.",
            central=True,
        ),
        Fact(
            id="F2",
            afirmacao="O hiato do produto segue positivo",
            numeros=[],
            doc_id="D1",
            citacao="hiato do produto positivo",
            central=True,
        ),
    ],
    implicacoes=["crédito mais barato"],
)


def test_syllables_portuguese():
    assert syllables("inflação") == 3 and syllables("econômica") == 4 and syllables("a") == 1


def test_readability_separates_official_from_simple_text():
    ata, simple = readability(ATA * 2), readability(SIMPLE * 2)
    assert ata.flesch < 25 < 60 < simple.flesch
    assert readability("Curto demais.").flesch is None  # below the minimum word count


@pytest.mark.parametrize(
    "text,explained",
    [
        (
            "O hiato do produto (a distância entre o que a economia produz e o que poderia) caiu.",
            True,
        ),
        ("O hiato do produto — ou seja, a folga da economia — caiu.", True),
        ("O hiato do produto caiu. Isso significa que a economia tem folga.", True),
        ("O hiato do produto caiu. Ou seja, a economia está aquecida demais.", True),
        (
            "O hiato do produto caiu e como resultado os juros recuaram.",
            False,
        ),  # "e como" ≠ "é como"
        ("O hiato do produto é como medir se a economia corre acima da velocidade normal.", True),
    ],
)
def test_explanation_detection(text, explained):
    report = analyze(text, G)
    assert ("hiato do produto" not in report.unexplained.get("avancado", [])) is explained


def test_term_explained_once_is_fine_later():
    text = "A Selic, que é a taxa básica de juros, caiu. Com a Selic menor, o crédito barateia."
    assert analyze(text, G).unexplained == {}


def test_analogies_counted_with_accents():
    assert analyze("Juros altos é como um freio. E como resultado, caem.", G).analogies == 1


def test_invented_number_is_flagged_and_coverage_measured():
    good = ground(
        "O Copom cortou a Selic para 13,75% e o hiato do produto segue positivo.", ANCHORS
    )
    assert good.ungrounded_numbers == [] and good.coverage == 1.0
    bad = ground("A Selic caiu para 12,25%.", ANCHORS)
    # a wrong figure does not count as covering the fact it contradicts
    assert bad.ungrounded_numbers == ["#12.25"] and bad.coverage == 0.0


def carousel(body_texts):
    roles = ["gancho"] + ["corpo"] * (len(body_texts) - 2) + ["conclusao"]
    return Carousel(
        slides=[
            Slide(papel=r, titulo=f"Slide {i}", texto=t)
            for i, (r, t) in enumerate(zip(roles, body_texts, strict=True))
        ],
        legenda="Entenda a decisão do Copom.",
        hashtags=["#selic"],
    )


def test_beginner_carousel_fails_on_unexplained_jargon_then_passes():
    jargon = carousel(
        [
            "O Copom cortou a Selic para 13,75%.",
            "O hiato do produto segue positivo, segundo o comitê.",
            "As expectativas desancoradas preocupam o mercado.",
            "O ciclo de cortes deve continuar com cautela.",
            "Decisões futuras dependem dos dados.",
            "Fique de olho na próxima reunião.",
        ]
    )
    report = evaluate("carrossel", "iniciante", jargon, ANCHORS, G)
    failed = {c.name for c in report.failures()}
    assert (
        "termos avancado sem explicação" in failed
        and "termos intermediario sem explicação" in failed
    )
    assert "hiato do produto" in report.feedback() and not report.passed

    explained = carousel(
        [
            "O Banco Central cortou a Selic, que é a taxa básica de juros, para 13,75%.",
            "O hiato do produto (a folga da economia) segue positivo. "
            "É como um carro acima da velocidade.",
            "As expectativas desancoradas, ou seja, quando as pessoas esperam mais inflação, "
            "preocupam.",
            "Por isso o corte é pequeno. O banco vai com calma.",
            "Assim o crédito fica um pouco mais barato. Comprar a prazo fica mais fácil.",
            "Fique de olho na próxima reunião. Ela pode trazer outro corte.",
        ]
    )
    report2 = evaluate("carrossel", "iniciante", explained, ANCHORS, G)
    names = {c.name: c.passed for c in report2.checks}
    assert names["termos avancado sem explicação"] and names["termos intermediario sem explicação"]
    assert names["números sem lastro na fonte"] and names["cobertura dos fatos centrais"]
    assert report2.score > report.score


def test_invented_number_zeroes_the_score():
    content = carousel(["A Selic caiu para 12%.", "a", "b", "c", "d", "e"])
    report = evaluate("carrossel", "avancado", content, ANCHORS, G)
    assert report.score == 0.0 and not report.passed


def test_script_format_rules():
    blocks = [
        ScriptBlock(inicio_s=0, fim_s=10, gancho_visual="x", fala="palavra " * 60),
        ScriptBlock(inicio_s=8, fim_s=30, gancho_visual="y", fala="palavra " * 60),
        ScriptBlock(inicio_s=30, fim_s=65 - 5, gancho_visual="z", fala="palavra " * 60),
    ]
    report = evaluate("roteiro", "intermediario", Script(titulo="t", blocos=blocks), ANCHORS, G)
    checks = {c.name: c for c in report.checks}
    assert not checks["palavras faladas"].passed  # 180 > 150
    assert not checks["linha do tempo"].passed  # overlap 8 < 10


def test_level_targets_file_is_consistent():
    cfg = level_targets()
    assert {"iniciante", "intermediario", "avancado", "formats"} <= set(cfg)
    assert cfg["iniciante"]["flesch_min"] > cfg["avancado"]["flesch_max"]


async def test_judge_check_is_attached(settings):
    import json

    import httpx

    from evals.evaluator import add_judge_check
    from evals.judge import judge
    from llm.router import LLMRouter, Provider
    from scraper.core.http import HttpClient

    verdicts = {
        "afirmacoes": [
            {"afirmacao": "O Copom cortou os juros", "veredito": "apoiada", "motivo": "F1"},
            {
                "afirmacao": "O corte foi pedido pelo presidente",
                "veredito": "nao_apoiada",
                "motivo": "não está nos fatos",
            },
        ]
    }

    def handler(request):
        assert "FATOS VERIFICADOS" in json.loads(request.content)["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(verdicts)}}],
                "usage": {"total_tokens": 10},
            },
        )

    router = LLMRouter(
        settings,
        http=HttpClient(settings, transport=httpx.MockTransport(handler)),
        providers=[Provider("groq", "m", "K", "k", 8000)],
    )
    result = await judge(router, "texto", ANCHORS)
    report = evaluate("carrossel", "intermediario", carousel(["a"] * 6), ANCHORS, G)
    add_judge_check(report, result)
    check = report.checks[-1]
    assert not check.passed and "presidente" in check.feedback


def test_format_overrides_relax_readability_for_spoken_scripts():
    from evals.evaluator import targets_for

    cfg = level_targets()
    assert targets_for("intermediario", "artigo", cfg)["flesch_max"] == 60
    assert targets_for("intermediario", "roteiro", cfg)["flesch_max"] == 80
    # untouched keys come from the level
    assert targets_for("intermediario", "roteiro", cfg)["unexplained_max"] == {"avancado": 0}

from glossary.matcher import Glossary, Term, fold_keep_length, load_glossary

G = Glossary(
    [
        Term("juros", "basico"),
        Term("juros futuros", "intermediario", ("DI futuro",)),
        Term("hiato do produto", "avancado", ("output gap",)),
        Term("CDI", "basico"),
        Term("política monetária", "intermediario"),
    ]
)


def names(text):
    return [h.term.termo for h in G.match(text)]


def test_fold_keeps_offsets():
    text = "Política monetária e ÇÃO"
    assert len(fold_keep_length(text)) == len(text)
    assert fold_keep_length(text) == "politica monetaria e cao"


def test_longest_match_wins():
    assert names("Os juros futuros subiram; os juros caíram.") == ["juros futuros", "juros"]


def test_accents_case_variants_and_line_breaks():
    assert names("A POLITICA MONETARIA e o Output\nGap") == [
        "política monetária",
        "hiato do produto",
    ]


def test_acronyms_are_case_sensitive_and_whole_word():
    assert names("O CDI rende; cdi minúsculo e CDIs não contam.") == ["CDI"]


def test_offsets_point_to_original_surface():
    hit = G.match("Sobre o hiato do produto.")[0]
    assert hit.surface == "hiato do produto"


def test_load_merges_reviewed_over_candidates(tmp_path):
    (tmp_path / "terms.yaml").write_text("- {termo: Selic, nivel: basico, revisado: true}\n")
    (tmp_path / "candidates.yaml").write_text(
        "- {termo: selic, nivel: avancado}\n- {termo: taxa terminal, nivel: avancado}\n"
    )
    load_glossary.cache_clear()
    full = load_glossary(True, tmp_path).by_name()
    assert full["Selic"].nivel == "basico" and "taxa terminal" in full
    assert "taxa terminal" not in load_glossary(False, tmp_path).by_name()


def test_loader_skips_non_jargon_and_resolves_acronym_conflicts(tmp_path):
    (tmp_path / "candidates.yaml").write_text(
        "- {termo: TIR, nivel: avancado, fonte: bcb, definicao: transferencias}\n"
        "- {termo: Taxa Interna de Retorno, nivel: avancado, fonte: manual, variantes: [TIR]}\n"
        "- {termo: cujo objetivo atingir, nivel: basico, e_jargao: false}\n"
        "- {termo: ruim, nivel: basico, rejeitado: true}\n"
    )
    load_glossary.cache_clear()
    g = load_glossary(True, tmp_path)
    assert set(g.by_name()) == {"Taxa Interna de Retorno"}
    assert g.match("A TIR do projeto")[0].term.termo == "Taxa Interna de Retorno"

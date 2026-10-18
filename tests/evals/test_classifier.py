from evals.batch import render_markdown
from evals.classifier import CentroidClassifier, accuracy, confusion, spec_level
from evals.evaluator import level_targets


def test_centroid_classifier_picks_nearest_reference():
    refs = {
        "avancado": [
            {"flesch": 30, "densidade_tecnica": 4, "analogias_100": 0, "nao_explicados_pct": 0.9}
        ]
        * 3,
        "intermediario": [
            {"flesch": 45, "densidade_tecnica": 1, "analogias_100": 0, "nao_explicados_pct": 0.5}
        ]
        * 3,
        "iniciante": [
            {"flesch": 65, "densidade_tecnica": 1, "analogias_100": 1.5, "nao_explicados_pct": 0.0}
        ],
    }
    clf = CentroidClassifier.fit(refs, {})
    assert (
        clf.predict(
            {"flesch": 33, "densidade_tecnica": 3.5, "analogias_100": 0, "nao_explicados_pct": 0.8}
        )
        == "avancado"
    )
    assert (
        clf.predict(
            {"flesch": 70, "densidade_tecnica": 0.8, "analogias_100": 2, "nao_explicados_pct": 0}
        )
        == "iniciante"
    )


def test_spec_level_rules():
    cfg = level_targets()
    beginner = {"flesch": 70, "nao_explicados": {}, "analogias": 2, "densidade_tecnica": 1}
    advanced = {
        "flesch": 33,
        "nao_explicados": {"avancado": ["x"]},
        "analogias": 0,
        "densidade_tecnica": 5,
    }
    assert spec_level(beginner, "artigo", cfg) == "iniciante"
    assert spec_level(advanced, "artigo", cfg) == "avancado"
    assert spec_level({**advanced, "flesch": 50}, "artigo", cfg) == "intermediario"


def test_confusion_and_report_markdown():
    pairs = [("iniciante", "iniciante"), ("avancado", "intermediario"), ("avancado", "avancado")]
    m = confusion(pairs)
    assert m["avancado"]["intermediario"] == 1 and accuracy(pairs) == 0.667
    report = {
        "generated_at": "x",
        "events": [{}],
        "rows": [],
        "new_generations": 0,
        "cached_generations": 0,
        "glossary_reviewed": False,
        "levels_version": "levels@1",
        "output_matrix_event": "Evento",
        "output_matrix": {"carrossel": {"iniciante": "a|b"}},
        "pass_rate": {},
        "confusion": {"spec": m, "centroid": m},
        "accuracy": {"spec": 0.667, "centroid": 0.667},
        "classifier_sources": {"a": "b"},
        "reflection": {
            "total": 0,
            "rewritten": 0,
            "fixed_by_rewrite": 0,
            "first_score": None,
            "final_score": None,
            "common_failures": [],
        },
        "cost": {
            "calls": 0,
            "failed_calls": 0,
            "in_tokens": 0,
            "out_tokens": 0,
            "by_purpose": {},
            "latency_by_format": {},
        },
    }
    md = render_markdown(report)
    assert "Matriz de confusão" in md and "a/b" in md  # pipe escaped inside table cells

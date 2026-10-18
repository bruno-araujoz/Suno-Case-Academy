"""Batch evaluation: formats × levels over the top-N events → report (TAPI deliverables 2 and 6).

Produces reports/<timestamp>/report.{json,md} with:
- the output matrix (same event and format, the three levels side by side);
- pass rate per level × format;
- confusion matrices: spec rules and the independent centroid classifier;
- reflection-loop gains (first vs. final attempt);
- LLM calls, tokens and latency per purpose and per format.
Reuses cached anchors/generations, so re-running only pays for what is new.
"""

from __future__ import annotations

import asyncio
import json
import statistics as st
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from generation.schemas import FORMATS, LEVELS, SCHEMAS, reader_text
from generation.service import GenerationResult, generate
from glossary.matcher import load_glossary
from llm.router import LLMError, LLMRouter, db_recorder
from scraper.core.config import get_settings
from scraper.core.db import Database
from scraper.core.http import HttpClient

from .classifier import (
    BEGINNER_PRIOR,
    CentroidClassifier,
    accuracy,
    confusion,
    features,
    labeled_texts,
    spec_level,
)
from .evaluator import level_targets

REPORTS = Path(__file__).resolve().parents[2] / "reports"


async def fit_classifier(db: Database, sample: int = 200) -> CentroidClassifier:
    glossary = load_glossary(True)
    async with db.pool.acquire() as conn:
        official = [
            r["content_text"]
            for r in await conn.fetch(
                "SELECT content_text FROM documents WHERE doc_type IN "
                "('copom_ata','copom_comunicado') AND status='ready' ORDER BY random() LIMIT $1",
                sample,
            )
        ]
        news = [
            r["content_text"]
            for r in await conn.fetch(
                "SELECT content_text FROM documents WHERE tier='news' AND status='ready' "
                "AND length(content_text) > 800 ORDER BY random() LIMIT $1",
                sample,
            )
        ]
    refs = {
        "avancado": [f for t in official if (f := features(t[:6000], glossary))],
        "intermediario": [f for t in news if (f := features(t[:6000], glossary))],
    }
    sources = {
        "avancado": f"{len(refs['avancado'])} atas/comunicados do Copom",
        "intermediario": f"{len(refs['intermediario'])} notícias de portais",
    }
    labeled = [f for t in labeled_texts()["iniciante"] if (f := features(t, glossary))]
    if labeled:
        refs["iniciante"] = labeled
        sources["iniciante"] = f"{len(labeled)} textos rotulados pelo time"
    else:
        refs["iniciante"] = [BEGINNER_PRIOR]
        sources["iniciante"] = "PROVISÓRIO: prior da escala de Martins (sem conjunto rotulado)"
    return CentroidClassifier.fit(refs, sources)


def _row(result: GenerationResult, clf: CentroidClassifier, cfg: dict) -> dict[str, Any]:
    glossary = load_glossary(True)
    content = SCHEMAS[result.fmt].model_validate(result.content)
    feats = features(reader_text(result.fmt, content), glossary)
    first = result.attempts[0]["eval"] if result.attempts else result.eval
    return {
        "event": result.event_title,
        "cluster_id": result.cluster_id,
        "fmt": result.fmt,
        "level": result.level,
        "passed": result.passed,
        "score": result.score,
        "attempts": len(result.attempts),
        "cached": result.cached,
        "latency_ms": result.latency_ms,
        "metrics": result.eval["metrics"],
        "first_score": first["score"],
        "first_flesch": first["metrics"].get("flesch"),
        "first_failures": [c["name"] for c in first["checks"] if not c["passed"]],
        "spec_level": spec_level(result.eval["metrics"], result.fmt, cfg),
        "centroid_level": clf.predict(feats) if feats else None,
        "features": feats,
        "content": result.content,
    }


def _excerpt(fmt: str, content: dict, limit: int = 380) -> str:
    model = SCHEMAS[fmt].model_validate(content)
    text = reader_text(fmt, model).replace("\n", " ")
    return (text[:limit] + "…") if len(text) > limit else text


def render_markdown(report: dict[str, Any]) -> str:
    out = [f"# Relatório de avaliação em lote — {report['generated_at']}", ""]
    out += [
        f"- Eventos: {len(report['events'])} · gerações: {len(report['rows'])} "
        f"(novas: {report['new_generations']}, cache: {report['cached_generations']})",
        f"- Glossário revisado pelo time: {'sim' if report['glossary_reviewed'] else 'NÃO'}",
        f"- Versão das metas: `{report['levels_version']}`",
        "",
    ]

    out += ["## Matriz de saídas (mesmo evento, níveis lado a lado)", ""]
    for fmt, cells in report["output_matrix"].items():
        out += [
            f"**{fmt}** — {report['output_matrix_event']}",
            "",
            "| iniciante | intermediário | avançado |",
            "|---|---|---|",
            "| " + " | ".join(cells.get(lvl, "—").replace("|", "/") for lvl in LEVELS) + " |",
            "",
        ]

    out += [
        "## Aprovação por nível × formato",
        "",
        "| nível | " + " | ".join(FORMATS) + " |",
        "|---|" + "---|" * len(FORMATS),
    ]
    for lvl in LEVELS:
        cells = [report["pass_rate"].get(lvl, {}).get(fmt, "—") for fmt in FORMATS]
        out.append(f"| {lvl} | " + " | ".join(str(c) for c in cells) + " |")
    out.append("")

    for key, title, note in [
        (
            "spec",
            "Matriz de confusão — regras de especificação",
            "Mesma régua que guiou a geração: mede o cumprimento da especificação "
            "(parcialmente circular).",
        ),
        (
            "centroid",
            "Matriz de confusão — classificador independente (centróides externos)",
            "Centróides: "
            + "; ".join(f"{k}: {v}" for k, v in report["classifier_sources"].items()),
        ),
    ]:
        m = report["confusion"][key]
        out += [
            f"## {title}",
            "",
            f"_{note}_",
            "",
            f"Acurácia: **{report['accuracy'][key]}**",
            "",
            "| pedido \\ previsto | iniciante | intermediário | avançado |",
            "|---|---|---|---|",
        ]
        out += [f"| {t} | " + " | ".join(str(m[t][p]) for p in LEVELS) + " |" for t in LEVELS]
        out.append("")

    j = report.get("judge") or {}
    if j.get("checked"):
        out += [
            "## Juiz LLM (afirmações sem número)",
            "",
            f"- Gerações verificadas: {j['checked']} · com alguma afirmação não apoiada: "
            f"{j['with_unsupported']} · total de afirmações não apoiadas: "
            f"{j['unsupported_total']}",
            *[f"  - “{e[:160]}”" for e in j.get("examples", [])],
            "",
        ]
    r = report["reflection"]
    out += [
        "## Reflection loop",
        "",
        f"- Gerações que precisaram reescrever: {r['rewritten']} de {r['total']}",
        f"- Aprovadas após reescrita: {r['fixed_by_rewrite']}",
        f"- Score médio 1ª tentativa → final (reescritas): {r['first_score']} → {r['final_score']}",
        f"- Falhas mais comuns na 1ª tentativa: {r['common_failures']}",
        "",
    ]

    c = report["cost"]
    out += [
        "## Custo e latência",
        "",
        f"- Chamadas de LLM no lote: {c['calls']} (falhas/failover: {c['failed_calls']})",
        f"- Tokens: {c['in_tokens']} entrada + {c['out_tokens']} saída",
        "- Planos gratuitos (Groq/Gemini): custo monetário 0; o limite é de cota (tokens/min, "
        "req/dia).",
        "",
        "| propósito | chamadas | tokens | latência mediana (ms) |",
        "|---|---|---|---|",
    ]
    out += [
        f"| {p} | {v['calls']} | {v['tokens']} | {v['p50_ms']} |"
        for p, v in c["by_purpose"].items()
    ]
    out += ["", "| formato | latência mediana por geração nova (s) |", "|---|---|"]
    out += [f"| {f} | {v} |" for f, v in c["latency_by_format"].items()]
    out.append("")
    return "\n".join(out)


async def run_batch(
    n_events: int = 3,
    *,
    force: bool = False,
    use_judge: bool = False,
    window_hours: int = 72,
    log=print,
    same_events_as: Path | None = None,
    levels: tuple[str, ...] = LEVELS,
) -> Path:
    settings = get_settings()
    cfg = level_targets()
    started_at = datetime.now(UTC)
    async with Database(settings) as db:
        await db.migrate()
        if same_events_as is not None:  # controlled comparison: same events as an older report
            raw = await asyncio.to_thread(Path(same_events_as).read_text, encoding="utf-8")
            old = json.loads(raw)
            events = []
            for e in old["events"]:
                info = await db.event_info(e["cluster_id"])
                if info:
                    events.append(dict(info))
        else:
            events = [dict(e) for e in await db.top_events(window_hours, limit=n_events)]
        if not events:
            raise RuntimeError("nenhum evento na janela; rode `scrape.py refresh`")
        log("Classificador: calibrando centróides no corpus…")
        clf = await fit_classifier(db)
        rows: list[dict[str, Any]] = []
        async with HttpClient(settings) as http:
            router = LLMRouter(settings, http=http, recorder=db_recorder(db))
            for e_idx, event in enumerate(events, 1):
                for fmt in FORMATS:
                    for level in levels:
                        t0 = time.perf_counter()
                        try:
                            result = await generate(
                                fmt,
                                level,
                                db=db,
                                router=router,
                                http=http,
                                refresh=False,
                                force=force,
                                use_judge=use_judge,
                                event=event["cluster_id"],
                            )
                        except (LLMError, ValueError) as exc:
                            log(f"  [{e_idx}/{len(events)}] {fmt}/{level}: FALHOU — {exc}")
                            continue
                        rows.append(_row(result, clf, cfg))
                        log(
                            f"  [{e_idx}/{len(events)}] {fmt:9} {level:13} "
                            f"{'✓' if result.passed else '✗'} score {result.score} "
                            f"tent. {len(result.attempts)} "
                            f"{'(cache)' if result.cached else f'{time.perf_counter() - t0:.0f}s'}"
                        )
        async with db.pool.acquire() as conn:
            calls = [
                dict(r)
                for r in await conn.fetch(
                    "SELECT purpose, ok, in_tokens, out_tokens, latency_ms FROM llm_calls "
                    "WHERE at >= $1",
                    started_at,
                )
            ]

    # --- aggregate
    pass_rate: dict[str, dict[str, str]] = defaultdict(dict)
    for lvl in LEVELS:
        for fmt in FORMATS:
            sel = [r for r in rows if r["level"] == lvl and r["fmt"] == fmt]
            if sel:
                pass_rate[lvl][fmt] = f"{sum(r['passed'] for r in sel)}/{len(sel)}"
    spec_pairs = [(r["level"], r["spec_level"]) for r in rows]
    cent_pairs = [(r["level"], r["centroid_level"]) for r in rows if r["centroid_level"]]
    rewritten = [r for r in rows if r["attempts"] > 1]
    fail_counter: Counter = Counter(name for r in rows for name in r["first_failures"])
    first_event = events[0]["cluster_id"]
    matrix = {
        fmt: {
            r["level"]: _excerpt(fmt, r["content"])
            for r in rows
            if r["cluster_id"] == first_event and r["fmt"] == fmt
        }
        for fmt in FORMATS
    }
    by_purpose: dict[str, dict[str, Any]] = {}
    for p in sorted({c["purpose"] for c in calls}):
        sel = [c for c in calls if c["purpose"] == p]
        by_purpose[p] = {
            "calls": len(sel),
            "tokens": sum((c["in_tokens"] or 0) + (c["out_tokens"] or 0) for c in sel),
            "p50_ms": int(st.median(c["latency_ms"] or 0 for c in sel)),
        }
    new_rows = [r for r in rows if not r["cached"]]
    from generation.graph import levels_version  # local import: avoids a cycle at module load

    report = {
        "generated_at": started_at.strftime("%Y-%m-%d %H:%M UTC"),
        "events": [{"cluster_id": e["cluster_id"], "title": e["title"]} for e in events],
        "levels_version": levels_version(),
        "glossary_reviewed": all(t.revisado for t in load_glossary(True).terms),
        "new_generations": len(new_rows),
        "cached_generations": len(rows) - len(new_rows),
        "output_matrix_event": events[0]["title"],
        "output_matrix": matrix,
        "pass_rate": pass_rate,
        "confusion": {"spec": confusion(spec_pairs), "centroid": confusion(cent_pairs)},
        "accuracy": {"spec": accuracy(spec_pairs), "centroid": accuracy(cent_pairs)},
        "classifier_sources": clf.sources,
        "classifier_centroids": clf.centroids,
        "judge": {
            "checked": sum("afirmacoes_nao_apoiadas" in r["metrics"] for r in rows),
            "with_unsupported": sum(
                bool(r["metrics"].get("afirmacoes_nao_apoiadas")) for r in rows
            ),
            "unsupported_total": sum(
                len(r["metrics"].get("afirmacoes_nao_apoiadas") or []) for r in rows
            ),
            "examples": [
                c for r in rows for c in (r["metrics"].get("afirmacoes_nao_apoiadas") or [])
            ][:5],
        },
        "reflection": {
            "total": len(rows),
            "rewritten": len(rewritten),
            "fixed_by_rewrite": sum(r["passed"] for r in rewritten),
            "first_score": round(st.mean(r["first_score"] for r in rewritten), 3)
            if rewritten
            else None,
            "final_score": round(st.mean(r["score"] for r in rewritten), 3) if rewritten else None,
            "common_failures": fail_counter.most_common(5),
        },
        "cost": {
            "calls": len(calls),
            "failed_calls": sum(not c["ok"] for c in calls),
            "in_tokens": sum(c["in_tokens"] or 0 for c in calls),
            "out_tokens": sum(c["out_tokens"] or 0 for c in calls),
            "by_purpose": by_purpose,
            "latency_by_format": {
                f: round(st.median(r["latency_ms"] for r in new_rows if r["fmt"] == f) / 1000, 1)
                for f in FORMATS
                if any(r["fmt"] == f for r in new_rows)
            },
        },
        "rows": rows,
    }
    out_dir = REPORTS / started_at.strftime("%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return out_dir

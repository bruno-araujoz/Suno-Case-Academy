import { getJSON } from "../api.js";
import { LEVEL_LABEL, clear, h } from "../dom.js";

const LEVELS = ["iniciante", "intermediario", "avancado"];
const FORMATS = ["artigo", "carrossel", "roteiro"];

function matrix(title, note, data, accuracy) {
  return h("section", { class: "panel" },
    h("h3", {}, title),
    h("p", { class: "xs muted" }, note),
    h("p", { class: "small" }, "Acurácia: ", h("strong", {}, accuracy)),
    h("table", { class: "matrix" },
      h("thead", {}, h("tr", {}, h("th", {}, "pedido \\ previsto"), LEVELS.map((l) => h("th", {}, LEVEL_LABEL[l])))),
      h("tbody", {}, LEVELS.map((t) => h("tr", {}, h("th", {}, LEVEL_LABEL[t]),
        LEVELS.map((p) => h("td", { class: t === p ? "diag" : "" }, data[t]?.[p] ?? 0)))))));
}

export async function renderReport(app, reportId = null) {
  app.append(h("span", { class: "kicker" }, "Avaliação em lote"),
    h("h1", { class: "page-title" }, "Relatório experimental"));
  let report;
  let list = [];
  try {
    [report, list] = await Promise.all([
      getJSON(reportId ? `/api/reports/${reportId}` : "/api/reports/latest"),
      getJSON("/api/reports"),
    ]);
  } catch (error) {
    app.append(h("div", { class: "empty" }, `${error.message}. Rode: uv run python evaluate.py batch --events 3`));
    return;
  }
  const select = h("select", { "aria-label": "Relatório", class: "btn",
    onchange: (e) => { clear(app); renderReport(app, e.target.value); } },
    list.map((r) => h("option", { value: r.id, selected: r.id === report.id || null },
      `${r.generated_at} · ${r.passed}/${r.generations} aprovadas · ` +
      `${r.complete ? "lote completo" : `só ${r.levels.map((l) => LEVEL_LABEL[l]).join(", ")}`}${r.judge ? " · com juiz" : ""}`)));
  app.append(h("div", { style: "margin-bottom:1rem" }, select));
  const rows = report.rows || [];
  const nLevels = new Set(rows.map((x) => x.level)).size;
  const passed = rows.filter((r) => r.passed).length;
  const r = report.reflection || {};
  const c = report.cost || {};
  app.append(
    h("p", { class: "page-sub" }, `${report.generated_at} · ${report.events.length} eventos × 3 formatos × ${nLevels} ${nLevels === 1 ? "nível" : "níveis"} · ` +
      `metas ${report.levels_version}`),
    h("div", { class: "kpis" },
      h("div", { class: "kpi" }, h("span", { class: "xs muted" }, "Aprovadas"), h("b", {}, `${passed}/${rows.length}`)),
      h("div", { class: "kpi" }, h("span", { class: "xs muted" }, "Acurácia independente"), h("b", {}, report.accuracy.centroid)),
      h("div", { class: "kpi" }, h("span", { class: "xs muted" }, "Reflexão (score)"),
        h("b", {}, r.first_score != null ? `${r.first_score} → ${r.final_score}` : "—")),
      h("div", { class: "kpi" }, h("span", { class: "xs muted" }, "Chamadas de LLM"), h("b", {}, c.calls ?? "—"))),
    h("div", { class: "grid-2" },
      matrix("Matriz — classificador independente", "Centróides externos: " +
        Object.entries(report.classifier_sources || {}).map(([k, v]) => `${k}: ${v}`).join("; "),
        report.confusion.centroid, report.accuracy.centroid),
      matrix("Matriz — regras da especificação", "Mesma régua que guiou a geração (parcialmente circular).",
        report.confusion.spec, report.accuracy.spec)),
    h("section", { class: "panel", style: "margin-top:1rem" },
      h("h3", {}, "Aprovação por nível × formato"),
      h("table", { class: "matrix" },
        h("thead", {}, h("tr", {}, h("th", {}, ""), FORMATS.map((f) => h("th", {}, f)))),
        h("tbody", {}, LEVELS.map((l) => h("tr", {}, h("th", {}, LEVEL_LABEL[l]),
          FORMATS.map((f) => h("td", {}, report.pass_rate?.[l]?.[f] ?? "—"))))))),
    h("section", { class: "panel" },
      h("h3", {}, "Matriz de saídas (mesmo evento, níveis lado a lado)"),
      h("p", { class: "small" }, report.output_matrix_event),
      ...Object.entries(report.output_matrix || {}).map(([fmt, cells]) => h("div", { style: "margin-top:.75rem" },
        h("strong", { class: "small" }, fmt),
        h("div", { class: "grid-2" }, LEVELS.map((l) => h("div", { class: "kpi" },
          h("span", { class: "xs muted" }, LEVEL_LABEL[l]), h("p", { class: "small" }, cells[l] || "—"))))))));
}

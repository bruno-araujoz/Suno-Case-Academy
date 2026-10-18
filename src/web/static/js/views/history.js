import { getJSON } from "../api.js";
import { FORMAT_LABEL, LEVEL_LABEL, fmtDate, h } from "../dom.js";

export async function renderHistory(app) {
  app.append(h("span", { class: "kicker" }, "Histórico"),
    h("h1", { class: "page-title" }, "Gerações recentes"),
    h("p", { class: "page-sub" }, "Toda geração fica registrada com tentativas, métricas e fontes."));
  const rows = await getJSON("/api/generations?limit=60");
  if (!rows.length) {
    app.append(h("div", { class: "empty" }, "Nenhuma geração ainda. ", h("a", { href: "#/" }, "Criar a primeira")));
    return;
  }
  app.append(h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Quando", "Tema / evento", "Formato", "Público", "Resultado", "Tentativas"]
      .map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((r) => h("tr", { class: "link", tabindex: "0",
      onclick: () => { location.hash = `#/geracao/${r.id}`; },
      onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/geracao/${r.id}`; } },
      h("td", { class: "muted" }, fmtDate(r.created_at)),
      h("td", {}, r.topic ? h("div", { class: "xs muted" }, `tema: “${r.topic}”`) : null, r.event_title),
      h("td", {}, FORMAT_LABEL[r.fmt] || r.fmt),
      h("td", {}, LEVEL_LABEL[r.level] || r.level),
      h("td", {}, h("span", { class: r.passed ? "badge badge--ok" : "badge badge--fail" },
        `${r.passed ? "aprovado" : "não atingiu"} · ${Number(r.score).toFixed(2)}`),
        r.demo ? h("span", { class: "badge", style: "margin-left:4px" }, "demo") : null),
      h("td", {}, r.attempts)))))));
}

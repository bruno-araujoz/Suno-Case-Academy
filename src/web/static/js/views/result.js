import { getJSON } from "../api.js";
import { FORMAT_LABEL, LEVEL_LABEL, clear, fmtDate, h } from "../dom.js";
import { articleText, renderArticle } from "../render/article.js";
import { carouselText, renderCarousel } from "../render/carousel.js";
import { renderScript, scriptText } from "../render/script.js";

const RENDER = { carrossel: renderCarousel, artigo: renderArticle, roteiro: renderScript };
const TEXT = { carrossel: carouselText, artigo: articleText, roteiro: scriptText };

// ---------------------------------------------------------------- live progress (SSE)

export function renderProgress(container) {
  const list = h("ol", { "aria-live": "polite" });
  const running = h("li", { class: "running" }, h("span", {}, "Iniciando…"));
  list.append(running);
  container.append(h("section", { class: "progress", "aria-label": "Progresso" }, list));
  return {
    step(info) {
      const cls = info.node === "evaluate" ? (info.passed ? "ok" : "fail") : "done";
      const li = h("li", { class: cls },
        h("span", {}, h("strong", {}, info.label),
          info.detail ? h("span", { class: "detail" }, ` — ${info.detail}`) : null,
          info.failures && info.failures.length
            ? h("div", { class: "detail xs" }, `falhou em: ${info.failures.join(", ")}`) : null));
      list.insertBefore(li, running);
      running.firstChild.textContent =
        info.node === "evaluate" && !info.passed ? "Reescrevendo com o relatório de falhas…" : "Processando…";
    },
    finish(ok = true) {
      running.remove();
      if (!ok) list.append(h("li", { class: "fail" }, h("span", {}, "Interrompido")));
    },
  };
}

// ---------------------------------------------------------------- result

function checksPanel(evalReport) {
  const checks = evalReport.checks || [];
  return h("section", { class: "panel" },
    h("h3", {}, "Avaliação por métricas"),
    h("div", { class: "score" },
      h("span", { class: "score__value" }, Number(evalReport.score).toFixed(2)),
      evalReport.passed
        ? h("span", { class: "badge badge--ok" }, "✓ aprovado")
        : h("span", { class: "badge badge--fail" }, "melhor tentativa — metas não atingidas")),
    h("ul", { class: "checks" }, checks.map((c) => h("li", {},
      h("span", { class: c.passed ? "mark-ok" : "mark-fail", "aria-label": c.passed ? "ok" : "falhou" },
        c.passed ? "✓" : "✗"),
      h("span", {}, pretty(c.name)),
      h("span", { class: "val" }, `${formatValue(c.value)} · ${c.target}`),
      !c.passed && c.feedback ? h("span", { class: "fb" }, c.feedback) : null))));
}

// Internal level keys → readable Portuguese in metric names.
const pretty = (name) => String(name).replace("intermediario", "intermediários")
  .replace("avancado", "avançados").replace("termos intermediários", "Termos intermediários")
  .replace("termos avançados", "Termos avançados");

function formatValue(value) {
  if (typeof value === "string" && value.includes("→")) {  // carousel structure: keep it short
    const roles = value.split("→").map((s) => s.trim());
    return `${roles.length} slides: ${roles[0]} … ${roles[roles.length - 1]}`;
  }
  if (Array.isArray(value)) return value.length ? value.map((v) => String(v).replace("#", "")).join(", ") : "0";
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(2);
  return value ?? "—";
}

function attemptsPanel(result) {
  if (!result.attempts || result.attempts.length < 2) return null;
  return h("section", { class: "panel" },
    h("h3", {}, `Reflexão — ${result.attempts.length} tentativas`),
    h("div", { class: "attempts" }, result.attempts.map((a) => {
      const failed = (a.eval.checks || []).filter((c) => !c.passed).map((c) => c.name);
      return h("details", { class: "attempt" },
        h("summary", {},
          h("span", {}, `#${a.n} · ${a.provider || ""}`),
          h("span", { class: a.eval.passed ? "badge badge--ok" : "badge badge--fail" },
            `score ${Number(a.eval.score).toFixed(2)}`)),
        h("p", { class: "xs muted" }, failed.length ? `Falhas: ${failed.join(", ")}` : "Sem falhas"),
        RENDER[result.fmt](a.content));
    })));
}

function factsPanel(result) {
  const docs = Object.fromEntries((result.evidence || []).map((e) => [e.id, e]));
  const facts = (result.anchors && result.anchors.fatos) || [];
  return h("section", { class: "panel" },
    h("h3", {}, "Fatos verificados na fonte"),
    result.anchors && result.anchors.evento ? h("p", { class: "small" }, result.anchors.evento) : null,
    h("ul", { class: "facts" }, facts.map((f) => {
      const doc = docs[f.doc_id] || {};
      return h("li", {},
        h("span", {}, f.central ? h("strong", {}, `${f.id} · `) : `${f.id} · `, f.afirmacao),
        h("blockquote", {}, `“${f.citacao}” — `,
          doc.url ? h("a", { href: doc.url, target: "_blank", rel: "noopener" }, doc.source) : f.doc_id));
    })),
    result.dropped && result.dropped.length
      ? h("p", { class: "xs muted" }, `${result.dropped.length} fato(s) descartado(s) por não conferirem com a fonte.`)
      : null,
    h("h3", { style: "margin-top:1rem" }, "Documentos usados"),
    h("ol", { class: "sources" }, (result.evidence || []).map((e) => h("li", {},
      h("a", { href: e.url, target: "_blank", rel: "noopener" }, e.title),
      h("span", { class: "muted xs" }, ` · ${e.source} · ${fmtDate(e.published_at)}`)))));
}

export function renderResult(container, result, { onRegenerate } = {}) {
  const text = TEXT[result.fmt](result.content);
  const copy = h("button", { class: "btn", type: "button", onclick: async () => {
    await navigator.clipboard.writeText(text);
    copy.textContent = "Copiado ✓";
    setTimeout(() => { copy.textContent = "Copiar texto"; }, 1500);
  } }, "Copiar texto");
  const download = h("button", { class: "btn", type: "button", onclick: () => {
    const blob = new Blob([JSON.stringify(result.content, null, 2)], { type: "application/json" });
    const a = h("a", { href: URL.createObjectURL(blob), download: `suno-${result.fmt}-${result.level}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
  } }, "Baixar JSON");

  container.append(
    h("div", { class: "result-head" },
      h("div", {},
        h("span", { class: "kicker" }, `${FORMAT_LABEL[result.fmt]} · ${LEVEL_LABEL[result.level]}`),
        h("h2", {}, result.event_title),
        h("div", { class: "event__meta" },
          h("span", {}, `${result.publishers || 1} veículo(s)`),
          result.topic ? h("span", {}, `tema: “${result.topic}”`) : h("span", {}, "assunto mais relevante"),
          h("span", {}, `${(result.latency_ms / 1000).toFixed(1)} s`),
          result.cached ? h("span", { class: "badge" }, "cache · 0 chamadas de LLM") : null,
          result.demo_reflection ? h("span", { class: "badge badge--fail" }, "modo demonstração") : null,
          !result.glossary_reviewed ? h("span", { class: "badge" }, "glossário em revisão") : null)),
      h("div", { class: "actions" }, copy, download,
        onRegenerate ? h("button", { class: "btn btn--ghost", type: "button", onclick: onRegenerate },
          "Gerar nova versão") : null)),
    h("div", { class: "result" },
      h("div", {}, RENDER[result.fmt](result.content)),
      h("aside", {}, checksPanel(result.eval), attemptsPanel(result), factsPanel(result))));
}

// ---------------------------------------------------------------- stored generation (#/geracao/:id)

export async function renderGeneration(app, id) {
  app.append(h("p", { class: "muted" }, h("span", { class: "spinner" }), " Carregando…"));
  const result = await getJSON(`/api/generations/${id}`);
  clear(app);
  app.append(h("a", { href: "#/historico", class: "small muted" }, "← Histórico"));
  renderResult(app, result);
}

import { h } from "../dom.js";

export function renderArticle(content) {
  return h("article", { class: "article" },
    h("h1", {}, content.titulo),
    h("p", { class: "lead" }, content.lead),
    (content.secoes || []).map((s) => [h("h2", {}, s.subtitulo), ...paragraphs(s.texto)]),
    ...paragraphs(content.conclusao));
}

const paragraphs = (text) =>
  String(text || "").split(/\n{2,}/).filter(Boolean).map((p) => h("p", {}, p));

export const articleText = (c) =>
  [c.titulo, c.lead, ...(c.secoes || []).flatMap((s) => [s.subtitulo, s.texto]), c.conclusao].join("\n\n");

import { h } from "../dom.js";

export function renderScript(content) {
  const blocks = content.blocos || [];
  const words = blocks.reduce((n, b) => n + b.fala.split(/\s+/).filter(Boolean).length, 0);
  return h("section", { class: "script" },
    h("p", { class: "script__title" }, content.titulo),
    blocks.map((b) => h("div", { class: "block" },
      h("div", { class: "block__time" }, `${b.inicio_s}–${b.fim_s}s`),
      h("div", {}, h("div", { class: "block__screen" }, b.gancho_visual), h("div", {}, b.fala)))),
    h("p", { class: "muted small" }, `${words} palavras faladas · ~${Math.round(words / 2.5)} s de fala`));
}

export const scriptText = (c) =>
  [c.titulo, ...(c.blocos || []).map((b) => `[${b.inicio_s}-${b.fim_s}s] (${b.gancho_visual})\n${b.fala}`)].join("\n\n");

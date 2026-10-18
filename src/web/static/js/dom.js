// Tiny DOM helpers. Content always goes through textContent (LLM/news text is untrusted).
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export const clear = (el) => { while (el.firstChild) el.removeChild(el.firstChild); return el; };

export function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

// "texto «destaque» texto" (ts_headline) → nodes with <mark>, without innerHTML.
export function highlighted(text) {
  const out = [];
  String(text || "").split(/(«[^»]*»)/).forEach((part) => {
    if (part.startsWith("«") && part.endsWith("»")) out.push(h("mark", {}, part.slice(1, -1)));
    else if (part) out.push(part);
  });
  return out;
}

export const LEVEL_LABEL = { iniciante: "Iniciante", intermediario: "Intermediário", avancado: "Avançado" };
export const FORMAT_LABEL = { carrossel: "Carrossel de Instagram", artigo: "Artigo analítico", roteiro: "Roteiro de vídeo curto" };

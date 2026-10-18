import { getJSON, postSSE } from "../api.js";
import { FORMAT_LABEL, LEVEL_LABEL, clear, fmtDate, h, highlighted } from "../dom.js";
import { renderProgress, renderResult } from "./result.js";

const FORMATS = [
  { id: "carrossel", icon: "▦", desc: "6 a 10 slides: gancho, corpo e conclusão." },
  { id: "artigo", icon: "¶", desc: "Texto analítico para web ou newsletter." },
  { id: "roteiro", icon: "▶", desc: "Roteiro de vídeo de até 60 s, com marcações de tempo." },
];
const LEVELS = [
  { id: "iniciante", desc: "Impacto no bolso; todo termo técnico vem explicado." },
  { id: "intermediario", desc: "Vocabulário de mercado (CDI, Selic, IPCA); alocação e tendências." },
  { id: "avancado", desc: "Jargão técnico pleno; foco analítico e metodológico." },
];
const MODES = [
  { id: "top", label: "Assunto mais relevante agora" },
  { id: "trending", label: "Escolher entre os assuntos em alta" },
  { id: "search", label: "Buscar um tema" },
];

// State survives navigation between views (but not a reload).
const state = { mode: "top", selected: null, query: "", fmt: "carrossel", level: "iniciante",
                options: { refresh: true, judge: false, force: false, demo_reflection: false } };
let trending = null;
let controller = null;

function eventCard(event, { selectable = false, onSelect } = {}) {
  const selected = selectable && state.selected && state.selected.cluster_id === event.cluster_id;
  const body = [
    h("div", { class: "event__title" }, event.title),
    h("div", { class: "event__meta" },
      h("span", {}, `${event.publishers || 1} veículo(s)`),
      h("span", {}, `${event.docs} doc.`),
      event.last_at ? h("span", {}, fmtDate(event.last_at)) : null,
      event.has_official ? h("span", { class: "badge badge--official" }, "fonte oficial") : null),
    event.snippet ? h("div", { class: "event__snippet" }, ...highlighted(event.snippet)) : null,
  ];
  if (!selectable) return h("div", { class: "event event--feature" }, ...body);
  return h("button", { class: "event", type: "button", role: "radio", "aria-checked": String(!!selected),
    onclick: () => onSelect(event) }, ...body);
}

function choiceTiles(items, current, label, onPick) {
  return h("div", { class: "tiles", role: "radiogroup", "aria-label": label },
    items.map((item) => h("button", { class: "tile", type: "button", role: "radio",
      "aria-checked": String(item.id === current), onclick: () => onPick(item.id) },
      item.icon ? h("div", { class: "tile__icon", "aria-hidden": "true" }, item.icon) : null,
      h("span", { class: "tile__title" }, item.label || FORMAT_LABEL[item.id] || LEVEL_LABEL[item.id]),
      h("span", { class: "tile__desc" }, item.desc))));
}

function step(num, title, ...content) {
  return h("section", { class: "step", "aria-labelledby": `step-${num}` },
    h("div", { class: "step__head" }, h("span", { class: "step__num" }, num),
      h("h2", { class: "step__title", id: `step-${num}` }, title)),
    ...content);
}

export async function renderCreate(app) {
  app.append(
    h("span", { class: "kicker" }, "Criar conteúdo"),
    h("h1", { class: "page-title" }, "Notícia do mercado, no nível certo para o seu público"),
    h("p", { class: "page-sub" }, "Escolha o tema, o formato e o público. O texto é escrito a partir " +
      "de fontes reais, conferido contra elas e avaliado por métricas antes de chegar até você."));
  const topicBox = h("div");
  const formatBox = h("div");
  const levelBox = h("div");
  const generateBtn = h("button", { class: "btn btn--primary btn--lg", type: "button" }, "Gerar conteúdo");
  const hint = h("p", { class: "xs muted", "aria-live": "polite" });
  const output = h("div", { id: "output" });
  const options = h("details", { class: "opts" }, h("summary", {}, "Opções avançadas"),
    ...[["refresh", "Atualizar fontes vencidas antes (até 20 s)"],
        ["judge", "Juiz LLM para afirmações sem número (mais lento)"],
        ["force", "Ignorar o cache e gerar de novo"],
        ["demo_reflection", "Demonstração da reflexão (1ª versão sem adaptação ao público)"]]
      .map(([key, text]) => h("label", {},
        h("input", { type: "checkbox", checked: state.options[key] || null,
          onchange: (e) => { state.options[key] = e.target.checked; } }), text)));

  app.append(
    step(1, "Sobre o quê?", topicBox),
    step(2, "Formato", formatBox),
    step(3, "Para quem?", levelBox),
    options, generateBtn, hint, output);

  const refreshButton = () => {
    const needsPick = state.mode !== "top" && !state.selected;
    generateBtn.disabled = needsPick;
    hint.textContent = needsPick ? "Escolha um assunto no passo 1 (ou use o mais relevante agora)." : "";
  };

  const drawFormats = () => clear(formatBox).append(
    choiceTiles(FORMATS, state.fmt, "Formato", (id) => { state.fmt = id; drawFormats(); }));
  const drawLevels = () => clear(levelBox).append(
    choiceTiles(LEVELS, state.level, "Público", (id) => { state.level = id; drawLevels(); }));

  const pick = (event) => {
    state.selected = { cluster_id: event.cluster_id, title: event.title };
    drawTopic();
  };

  async function drawTopic() {
    clear(topicBox);
    topicBox.append(h("div", { class: "modes", role: "group", "aria-label": "Como escolher o tema" },
      MODES.map((m) => h("button", { class: "chip", type: "button", "aria-pressed": String(state.mode === m.id),
        onclick: () => { state.mode = m.id; state.selected = null; drawTopic(); } }, m.label))));
    const body = h("div");
    topicBox.append(body);
    refreshButton();

    if (trending === null) {
      body.append(h("p", { class: "muted small" }, h("span", { class: "spinner" }), " Carregando assuntos…"));
      try { trending = await getJSON("/api/events?limit=7"); } catch { trending = []; }
      clear(body);
    }
    if (state.mode === "top") {
      if (!trending.length) {
        body.append(h("div", { class: "empty" }, "Nenhum assunto recente no banco. Ao gerar, as fontes são atualizadas."));
      } else {
        body.append(h("p", { class: "small muted" }, "Para quem não sabe o tema: o conteúdo sai sobre o assunto que " +
          "mais veículos estão cobrindo agora."), eventCard(trending[0]));
      }
    } else if (state.mode === "trending") {
      body.append(h("div", { class: "events", role: "radiogroup", "aria-label": "Assuntos em alta" },
        trending.map((e) => eventCard(e, { selectable: true, onSelect: pick }))));
    } else {
      drawSearch(body);
    }
  }

  function drawSearch(body) {
    const input = h("input", { type: "search", placeholder: "Ex.: Petrobras, dividendos, Copom, bitcoin…",
      value: state.query, "aria-label": "Tema", autocomplete: "off" });
    const results = h("div", { class: "events", role: "radiogroup", "aria-label": "Resultados", "aria-live": "polite" });
    let timer = null;
    let seq = 0;
    const run = async (expand = false) => {
      const q = input.value.trim();
      state.query = q;
      if (q.length < 2) { clear(results); return; }
      const mine = ++seq;
      clear(results).append(h("p", { class: "muted small" }, h("span", { class: "spinner" }),
        expand ? " Buscando nos portais (Suno, InfoMoney, Money Times, Seu Dinheiro)…" : " Buscando…"));
      let data;
      try {
        data = await getJSON(`/api/topics/search?q=${encodeURIComponent(q)}${expand ? "&expand=1" : ""}`);
      } catch (error) {
        clear(results).append(h("div", { class: "notice" }, error.message));
        return;
      }
      if (mine !== seq) return; // a newer search already started
      clear(results);
      if (data.events.length) {
        if (data.expanded) results.append(h("p", { class: "xs muted" },
          `${data.fetched} artigo(s) novo(s) trazido(s) dos portais.`));
        results.append(...data.events.map((e) => eventCard(e, { selectable: true,
          onSelect: (ev) => { state.selected = { cluster_id: ev.cluster_id, title: ev.title, topic: q }; drawTopic(); } })));
        return;
      }
      results.append(h("div", { class: "empty" },
        data.expanded ? `Nada recente sobre “${q}” nem nos portais.` : `Nada sobre “${q}” no banco.`,
        !data.expanded ? h("button", { class: "btn", type: "button", onclick: () => run(true) }, "Buscar nos portais") : null,
        h("button", { class: "btn btn--ghost", type: "button",
          onclick: () => { state.mode = "top"; state.selected = null; drawTopic(); } },
          "Usar o assunto mais relevante")));
    };
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => run(false), 350); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); run(false); } });
    const form = h("div", { class: "search" }, input,
      h("button", { class: "btn", type: "button", onclick: () => run(false) }, "Buscar"));
    body.append(form, results);
    if (state.selected) {
      results.append(h("p", { class: "small" }, "Selecionado: ", h("strong", {}, state.selected.title)));
    } else if (state.query) {
      run(false);
    }
    input.focus();
  }

  async function generate(force = false) {
    if (controller) controller.abort();
    controller = new AbortController();
    generateBtn.disabled = true;
    generateBtn.textContent = "Gerando…";
    clear(output);
    const progress = renderProgress(output);
    output.scrollIntoView({ behavior: "smooth", block: "start" });
    const body = {
      fmt: state.fmt, level: state.level,
      cluster_id: state.mode === "top" ? null : state.selected?.cluster_id ?? null,
      topic: state.mode === "search" ? state.selected?.topic ?? state.query : null,
      options: { ...state.options, force: force || state.options.force },
    };
    let finished = false;
    try {
      await postSSE("/api/generate", body, (name, data) => {
        if (name === "progress") progress.step(data);
        else if (name === "result") {
          finished = true;
          progress.finish();
          renderResult(output, data, { onRegenerate: () => generate(true) });
        } else if (name === "error") {
          finished = true;
          progress.finish(false);
          output.append(h("div", { class: "notice" }, data.message));
        }
      }, controller.signal);
      if (!finished) {
        progress.finish(false);
        output.append(h("div", { class: "notice" }, "A conexão terminou antes do resultado."));
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        progress.finish(false);
        output.append(h("div", { class: "notice" }, `Falha na geração: ${error.message}`));
      }
    } finally {
      generateBtn.textContent = "Gerar conteúdo";
      refreshButton();
    }
  }

  generateBtn.addEventListener("click", () => generate(false));
  drawFormats();
  drawLevels();
  await drawTopic();
}

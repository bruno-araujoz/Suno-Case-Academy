// Hash router: views render into <main> without reloading the page.
import { renderCreate } from "./views/create.js";
import { renderHistory } from "./views/history.js";
import { renderReport } from "./views/report.js";
import { renderGeneration } from "./views/result.js";
import { clear, h } from "./dom.js";

const app = document.getElementById("app");
const routes = [
  { re: /^#?\/?$/, name: "create", view: () => renderCreate(app) },
  { re: /^#\/historico$/, name: "history", view: () => renderHistory(app) },
  { re: /^#\/relatorio$/, name: "report", view: () => renderReport(app) },
  { re: /^#\/geracao\/(\d+)$/, name: "history", view: (m) => renderGeneration(app, Number(m[1])) },
];

async function navigate() {
  const hash = location.hash || "#/";
  const route = routes.find((r) => r.re.test(hash)) || routes[0];
  document.querySelectorAll(".nav a").forEach((a) => {
    if (a.dataset.route === route.name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  clear(app);
  try {
    await route.view(hash.match(route.re));
  } catch (error) {
    app.append(h("div", { class: "notice" }, `Não foi possível carregar: ${error.message}`));
  }
  app.focus({ preventScroll: true });
}

window.addEventListener("hashchange", navigate);
navigate();

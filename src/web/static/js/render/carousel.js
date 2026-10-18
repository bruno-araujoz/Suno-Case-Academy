import { h } from "../dom.js";

const ROLE = { gancho: "Gancho", corpo: "", conclusao: "Conclusão" };

// Instagram-like 1:1 slides with arrows, dots and keyboard navigation.
export function renderCarousel(content) {
  const slides = content.slides || [];
  let index = 0;
  const track = h("div", { class: "carousel__track" },
    slides.map((s, i) => h("article", { class: `slide slide--${s.papel}`, "aria-roledescription": "slide",
      "aria-label": `${i + 1} de ${slides.length}` },
      ROLE[s.papel] ? h("span", { class: "slide__role" }, ROLE[s.papel]) : null,
      h("h3", { class: "slide__title" }, s.titulo),
      h("p", { class: "slide__text" }, s.texto),
      h("span", { class: "slide__count" }, `${i + 1}/${slides.length}`))));
  const dots = h("div", { class: "dots", "aria-hidden": "true" }, slides.map(() => h("span")));
  const go = (i) => {
    index = (i + slides.length) % slides.length;
    track.style.transform = `translateX(-${index * 100}%)`;
    [...dots.children].forEach((d, k) => d.classList.toggle("on", k === index));
  };
  const root = h("section", { class: "carousel", tabindex: "0", "aria-label": "Carrossel",
    onkeydown: (e) => { if (e.key === "ArrowRight") go(index + 1); if (e.key === "ArrowLeft") go(index - 1); } },
    h("div", { class: "carousel__viewport" }, track),
    h("div", { class: "carousel__nav" },
      h("button", { type: "button", "aria-label": "Slide anterior", onclick: () => go(index - 1) }, "‹"),
      dots,
      h("button", { type: "button", "aria-label": "Próximo slide", onclick: () => go(index + 1) }, "›")),
    h("div", { class: "caption" },
      h("div", {}, h("strong", {}, "Legenda: "), content.legenda || ""),
      h("div", { class: "tags" }, (content.hashtags || []).join(" "))));
  go(0);
  return root;
}

export const carouselText = (c) =>
  [...(c.slides || []).map((s, i) => `${i + 1}. ${s.titulo}\n${s.texto}`), "", c.legenda,
   (c.hashtags || []).join(" ")].join("\n\n");

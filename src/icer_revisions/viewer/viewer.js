// Extraction viewer: PDF pages on the left, each extractor's fields and quotes on the right.
// All data comes from the local server in view.py; quote boxes are found there (locate.py), so this only draws.
import * as pdfjs from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.min.mjs";

pdfjs.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/pdf.worker.min.mjs";

const $ = (s) => document.querySelector(s);
const GROUP_TITLES = {
  icers: "ICERs, costs and QALYs",
  stepwise: "Agency's stepped analysis",
  features: "Submission features",
  price: "Price reduction",
};
const DOC_TITLES = { rec: "Recommendation", pe: "Economic report", clin: "Clinical report" };
const STATUS = {
  found: "✓",
  other_page: "other page",
  other_document: "other document",
  partial: "partial",
  not_found: "not found",
  no_document: "no document",
};

const state = { review: null, shown: [], pdfs: {}, kind: null, page: 1, selected: null, draw: 0 };

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined));
  return node;
};

const shortName = (x) => `${x.model.split("/").pop()} · ${x.id.split("-").pop()}`;
const shownExtractors = () => state.review.extractors.filter((x) => state.shown.includes(x.id));
const colour = (x) => `c${Math.max(0, shownExtractors().indexOf(x))}`;
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function format(value) {
  if (value === null || value === undefined) return el("span", { class: "null" }, "—");
  if (Array.isArray(value)) {
    if (!value.length) return el("span", { class: "null" }, "none");
    const money = (v) => (v === null || v === undefined ? "—" : `$${Math.round(v).toLocaleString()}`);
    const qaly = (v) => (v === null || v === undefined ? "—" : v.toLocaleString());
    return el("ol", { class: "steps" }, value.map((r) => el("li", {},
      r.label, " ",
      el("span", { class: "muted" }, `[${r.row_type}${r.category ? `: ${r.category}` : ""}]`),
      el("div", { class: "muted" },
        r.cost_drug !== null || r.cost_comparator !== null
          ? `drug ${money(r.cost_drug)}, ${qaly(r.qaly_drug)} QALYs; comparator ${money(r.cost_comparator)}, ${qaly(r.qaly_comparator)} QALYs`
          : `incremental ${money(r.inc_cost)}, ${qaly(r.inc_qaly)} QALYs`,
        `; ICER ${money(r.icer)}${r.icer_note === "point" ? "" : ` (${r.icer_note})`}; ${r.analysis ?? ""}`))));
  }
  if (typeof value === "number") return document.createTextNode(value.toLocaleString());
  return document.createTextNode(String(value));
}

function chip(x, ev) {
  const cited = `${ev.row ? `row ${ev.row}: ` : ""}${ev.document} p.${ev.page}`;
  const label = {
    other_page: `${cited} → p.${ev.page_found}`,
    other_document: `${cited} → ${ev.document_found} p.${ev.page_found}`,
  }[ev.status] ?? `${cited} ${STATUS[ev.status]}`;
  return el("button", {
    class: `chip ${colour(x)} ${state.selected === ev ? "selected" : ""}`,
    title: `"${ev.quote}" (match ${Math.round(ev.score * 100)}%)`,
    onclick: () => select(ev),
  }, el("span", { class: ev.status }, label));
}

function renderPanel() {
  const xs = shownExtractors();
  const panel = $("#panel");
  panel.replaceChildren();
  for (const x of xs) {
    const counts = {};
    for (const ev of x.evidence) counts[ev.status] = (counts[ev.status] || 0) + 1;
    const calls = Object.entries(x.calls).map(([g, c]) => `${g} ${c.error ? "failed" : c.seconds ? `${Math.round(c.seconds)}s` : "ok"}`);
    panel.append(el("div", { class: `summary ${colour(x)}` },
      el("span", { class: "swatch" }), el("strong", {}, shortName(x)),
      ` · $${(x.cost_usd || 0).toFixed(3)} · ${calls.join(", ")}`,
      x.error ? el("div", { class: "not_found" }, x.error) : null,
      el("div", { class: "muted" }, "Quotes: ", Object.entries(counts).map(([s, n]) => `${n} ${STATUS[s]}`).join(" · ") || "none")));
  }
  const known = new Set();
  for (const group of state.review.fields) {
    panel.append(el("h2", {}, GROUP_TITLES[group.group] || group.group));
    const rows = group.fields.map((f) => {
      known.add(f.name);
      const values = xs.map((x) => x.values[f.name]);
      const differs = xs.length > 1 && values.some((v) => !same(v, values[0]));
      return el("tr", { class: differs ? "diff" : "" },
        el("td", { class: "field" }, el("abbr", { title: f.description }, f.name)),
        xs.map((x) => el("td", {},
          el("div", { class: "value" }, format(x.values[f.name])),
          el("div", { class: "chips" }, x.evidence.filter((ev) => ev.fields.includes(f.name)).map((ev) => chip(x, ev))))));
    });
    panel.append(el("table", {}, el("tr", {}, el("th", {}, "Field"), xs.map((x) =>
      el("th", { class: colour(x) }, el("span", { class: "swatch" }), shortName(x)))), rows));
  }
  const stray = xs.flatMap((x) => x.evidence.filter((ev) => !ev.fields.some((f) => known.has(f))).map((ev) => [x, ev]));
  if (stray.length) {
    panel.append(el("h2", {}, "Quotes for other fields"),
      el("div", { class: "chips" }, stray.map(([x, ev]) => chip(x, ev))));
  }
  for (const x of xs) {
    panel.append(el("h2", { class: colour(x) }, el("span", { class: "swatch" }), `Notes: ${shortName(x)}`),
      el("div", { class: "notes" }, x.notes.length ? x.notes.map((n) => `${n.group}: ${n.text}\n`) : "none"));
  }
}

function pdf(kind) {
  state.pdfs[kind] ??= pdfjs.getDocument(`/pdf/${state.review.project}/${kind}.pdf`).promise;
  return state.pdfs[kind];
}

async function showPage(kind, page) {
  if (!kind) return;
  const draw = ++state.draw;
  const doc = await pdf(kind);
  page = Math.min(Math.max(1, page), doc.numPages);
  const p = await doc.getPage(page);
  const width = $("#pdf-wrap").clientWidth - 24;
  const scale = width / p.getViewport({ scale: 1 }).width;
  const viewport = p.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;
  const canvas = document.createElement("canvas");
  canvas.id = "canvas";
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  await p.render({ canvasContext: canvas.getContext("2d"), viewport, transform: [ratio, 0, 0, ratio, 0, 0] }).promise;
  if (draw !== state.draw) return; // a newer page was asked for while this one rendered
  Object.assign(state, { kind, page });
  $("#page-label").textContent = `${DOC_TITLES[kind]}, page ${page} of ${doc.numPages}`;
  for (const b of document.querySelectorAll("#doc-tabs button")) b.classList.toggle("on", b.dataset.kind === kind);
  $("#page").style.width = `${viewport.width}px`;
  $("#canvas").replaceWith(canvas);
  drawBoxes(scale);
}

function drawBoxes(scale) {
  const layer = $("#boxes");
  layer.replaceChildren();
  let target = null;
  for (const x of shownExtractors()) {
    for (const ev of x.evidence) {
      if (ev.document_found !== state.kind || ev.page_found !== state.page) continue;
      for (const [x0, y0, x1, y1] of ev.boxes) {
        const box = el("div", {
          class: `box ${colour(x)} ${state.selected === ev ? "selected" : ""}`,
          title: `${ev.fields.join(", ")} (${shortName(x)})`,
          onclick: () => select(ev),
        });
        Object.assign(box.style, {
          left: `${x0 * scale - 1}px`, top: `${y0 * scale - 1}px`,
          width: `${(x1 - x0) * scale + 2}px`, height: `${(y1 - y0) * scale + 2}px`,
        });
        layer.append(box);
        if (state.selected === ev) target ??= box;
      }
    }
  }
  target?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function select(ev) {
  state.selected = ev;
  const quote = $("#quote");
  quote.hidden = false;
  const where = {
    found: `on page ${ev.page_found}, as cited`,
    other_page: `cited as page ${ev.page}, found on page ${ev.page_found}`,
    partial: `only ${Math.round(ev.score * 100)}% of its words found, best on page ${ev.page_found}`,
    other_document: `cited as ${ev.document} page ${ev.page}, found in the ${DOC_TITLES[ev.document_found]}, page ${ev.page_found}`,
    not_found: "not found in any attached document: showing the cited page",
    no_document: "the cited document is not attached",
  }[ev.status];
  quote.replaceChildren(el("strong", {}, ev.fields.join(", ")), `: "${ev.quote}" `, el("span", { class: ev.status }, `(${where})`));
  renderPanel();
  if (ev.document_found) showPage(ev.document_found, ev.page_found);
  else if (state.review.documents.includes(ev.document)) showPage(ev.document, ev.page);
}

function renderExtractorPicker() {
  const box = $("#extractors");
  box.replaceChildren(...state.review.extractors.map((x) => el("label", {},
    el("input", {
      type: "checkbox",
      ...(state.shown.includes(x.id) ? { checked: "" } : {}),
      onchange: (e) => {
        state.shown = e.target.checked ? [...state.shown, x.id] : state.shown.filter((id) => id !== x.id);
        state.shown = state.review.extractors.map((y) => y.id).filter((id) => state.shown.includes(id));
        renderPanel();
        showPage(state.kind, state.page);
      },
    }), ` ${shortName(x)}`)));
}

async function openReview(project) {
  state.review = await (await fetch(`/api/review/${project}`)).json();
  Object.assign(state, { pdfs: {}, selected: null });
  const models = new Set(); // newest record of each model is shown by default (records come newest first)
  state.shown = state.review.extractors.filter((x) => !models.has(x.model) && models.add(x.model)).map((x) => x.id).slice(0, 2);
  location.hash = project;
  $("#quote").hidden = true;
  $("#doc-tabs").replaceChildren(...state.review.documents.map((k) =>
    el("button", { "data-kind": k, title: DOC_TITLES[k], onclick: () => showPage(k, 1) }, k)));
  renderExtractorPicker();
  renderPanel();
  await showPage(state.review.documents[0], 1);
}

async function main() {
  const reviews = await (await fetch("/api/reviews")).json();
  const pick = $("#review");
  pick.replaceChildren(...reviews.map((r) => el("option", { value: r.project }, `${r.project} (${r.extractors.length})`)));
  pick.onchange = () => openReview(pick.value);
  $("#prev").onclick = () => showPage(state.kind, state.page - 1);
  $("#next").onclick = () => showPage(state.kind, state.page + 1);
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, select")) return;
    if (e.key === "ArrowLeft") showPage(state.kind, state.page - 1);
    if (e.key === "ArrowRight") showPage(state.kind, state.page + 1);
  });
  let resize;
  window.addEventListener("resize", () => {
    clearTimeout(resize);
    resize = setTimeout(() => state.kind && showPage(state.kind, state.page), 150);
  });
  if (!reviews.length) {
    $("#panel").replaceChildren(el("p", { class: "muted" }, "No extraction records yet: run `icer extract` first."));
    return;
  }
  const wanted = location.hash.slice(1);
  pick.value = reviews.some((r) => r.project === wanted) ? wanted : reviews[0].project;
  await openReview(pick.value);
}

main();

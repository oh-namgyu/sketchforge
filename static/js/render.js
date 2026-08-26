"use strict";

/* The render canvas: mermaid parse, mermaid render, sanitise, insert.

   Two mermaid settings carry weight here.

   securityLevel 'strict' is the library's own sanitiser and the first of the
   four defence layers. bindFunctions — the callback mermaid hands back so a
   page can wire up `click` directives — is deliberately never called, so a
   `click X call something()` in a source is inert even before sanitising.

   htmlLabels is off. With it on, mermaid wraps labels in <foreignObject> and
   HTML, which the allowlist strips — the diagram would render with empty
   nodes. Off, labels come out as <text>, which survives sanitising intact. */

const SFRender = (window.SFRender = {});

const MERMAID_CONFIG = {
  startOnLoad: false,
  securityLevel: "strict",
  theme: "neutral",
  htmlLabels: false,
  fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
  flowchart: { htmlLabels: false, useMaxWidth: true, curve: "basis" },
  class: { htmlLabels: false, useMaxWidth: true },
  sequence: { useMaxWidth: true },
  er: { useMaxWidth: true },
  state: { useMaxWidth: true },
};

const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.2;

let renderSeq = 0;
let ready = false;

function init() {
  if (ready) return;
  window.mermaid.initialize(MERMAID_CONFIG);
  ready = true;
}

function messageOf(err) {
  if (!err) return "render failed";
  return String(err.str || err.message || err);
}

/* Parse first so a syntax error arrives as a thrown message instead of
   mermaid's own error graphic, then render, then sanitise. Nothing reaches the
   document that has not been through SFSanitize.sanitizeSvg. */
async function toSvgElement(source) {
  init();
  await window.mermaid.parse(source);
  renderSeq += 1;
  const result = await window.mermaid.render("sf-render-" + renderSeq, source);
  const node = window.SFSanitize.sanitizeSvg(result.svg);
  if (!node) throw new Error("renderer produced no usable svg");
  node.removeAttribute("width");
  node.setAttribute("class", "diagram-svg");
  return node;
}

/* A canvas owns one stage element; zoom and pan are a transform on it, applied
   through the CSSOM rather than a style attribute in markup. */
function createCanvas(options) {
  const stage = options.stage;
  const container = options.container;
  const view = { zoom: 1, x: 0, y: 0 };
  let dragging = null;

  function apply() {
    stage.style.transform =
      "translate(" + view.x + "px, " + view.y + "px) scale(" + view.zoom + ")";
    if (options.onView) options.onView(view);
  }

  function setZoom(next) {
    view.zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(next * 100) / 100));
    apply();
  }

  container.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    dragging = { x: event.clientX - view.x, y: event.clientY - view.y };
    container.setPointerCapture(event.pointerId);
    container.classList.add("is-panning");
  });
  container.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    view.x = event.clientX - dragging.x;
    view.y = event.clientY - dragging.y;
    apply();
  });
  ["pointerup", "pointercancel"].forEach((name) =>
    container.addEventListener(name, (event) => {
      dragging = null;
      container.classList.remove("is-panning");
      if (container.hasPointerCapture(event.pointerId)) {
        container.releasePointerCapture(event.pointerId);
      }
    })
  );

  return {
    view: view,
    zoomIn: () => setZoom(view.zoom + ZOOM_STEP),
    zoomOut: () => setZoom(view.zoom - ZOOM_STEP),
    reset: () => {
      view.x = 0;
      view.y = 0;
      setZoom(1);
    },
    /* The single markup insertion point of the whole application. */
    show: (element) => {
      stage.replaceChildren(element);
    },
    clear: () => stage.replaceChildren(),
  };
}

Object.assign(SFRender, {
  init: init,
  toSvgElement: toSvgElement,
  createCanvas: createCanvas,
  messageOf: messageOf,
  MERMAID_CONFIG: MERMAID_CONFIG,
});

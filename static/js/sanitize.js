"use strict";

/* sanitizeSvg — the one place sketchforge is allowed to build markup from a
   string, and the security boundary for the render path.

   It is an ALLOWLIST, not a blocklist: an element survives only if it is in
   the SVG namespace and its name is listed below, and an attribute survives
   only if its name is listed (or carries an aria- or data- prefix). Everything
   else — every
   on* handler, <script>, <foreignObject>, any HTML that rode in on a label —
   is dropped without being asked what it is. A blocklist would have to keep up
   with mermaid's input language; an allowlist only has to keep up with the SVG
   features a diagram actually uses.

   The same function runs before insertion and before export, so there is no
   way for the two paths to disagree about what "sanitised" means.

   It is one of four layers, not the only one: mermaid runs with
   securityLevel 'strict', bindFunctions is never called, the response CSP is
   script-src 'self', and the e2e suite fires probes at all of it. */

const SVG_NS = "http://www.w3.org/2000/svg";

/* Presentation elements a mermaid diagram is built from. Deliberately absent:
   foreignObject (an HTML escape hatch), script, image, animate*, set, and
   anything else that can fetch, script or move. */
const ALLOWED_ELEMENTS = new Set([
  "svg", "g", "defs", "desc", "title", "style", "symbol", "use", "a",
  "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
  "text", "tspan", "textpath",
  "marker", "clippath", "mask", "pattern",
  "lineargradient", "radialgradient", "stop",
  "filter", "fegaussianblur", "feoffset", "feblend", "fecolormatrix",
  "fecomposite", "feflood", "femerge", "femergenode", "fedropshadow",
]);

/* Geometry, paint, text and layout attributes. No event handlers can pass:
   none of these start with "on", and a leading-"on" test rejects them anyway. */
const ALLOWED_ATTRS = new Set([
  "id", "class", "style", "transform", "transform-origin",
  "d", "points", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
  "width", "height", "dx", "dy", "viewbox", "preserveaspectratio",
  "fill", "fill-opacity", "fill-rule", "opacity", "color",
  "stroke", "stroke-width", "stroke-opacity", "stroke-dasharray",
  "stroke-dashoffset", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
  "font-family", "font-size", "font-weight", "font-style", "font-variant",
  "letter-spacing", "word-spacing", "text-anchor", "text-decoration",
  "dominant-baseline", "alignment-baseline", "baseline-shift", "white-space",
  "marker-start", "marker-mid", "marker-end", "orient",
  "refx", "refy", "markerwidth", "markerheight", "markerunits",
  "offset", "stop-color", "stop-opacity", "spreadmethod",
  "gradientunits", "gradienttransform", "patternunits", "patterntransform",
  "clip-path", "clip-rule", "clippathunits", "mask", "maskunits", "filter",
  "in", "in2", "mode", "result", "stddeviation", "flood-color", "flood-opacity",
  "type", "values", "operator", "k1", "k2", "k3", "k4",
  "shape-rendering", "text-rendering", "vector-effect", "overflow", "display",
  "visibility", "pointer-events", "cursor", "role", "xmlns", "xmlns:xlink",
  "version", "space", "xml:space", "lang", "xml:lang",
]);

/* href is the only attribute that can name a destination, so it is the only
   one with a value policy: same-document anchors and http(s) links, nothing
   else — no javascript:, no data:, no blob:. */
const URL_ATTRS = new Set(["href", "xlink:href"]);
const SAFE_URL = /^(#[^\s]*|https?:\/\/\S*)$/i;
const PREFIX_ATTRS = /^(aria-|data-)/;
const CSS_URL = /url\(\s*(['"]?)([^)'"]*)\1\s*\)/gi;

/* CSS cannot script under our CSP, but it can still phone home through an
   external url(). Local references (url(#marker)) are what mermaid needs and
   all it gets. */
function sanitizeCss(css) {
  return String(css || "")
    .replace(/@import[^;]*;?/gi, "")
    .replace(/expression\s*\(/gi, "(")
    .replace(CSS_URL, (whole, quote, target) => {
      const value = String(target).trim();
      return value.startsWith("#") ? "url(" + value + ")" : "none";
    })
    .replace(/javascript\s*:/gi, "");
}

function safeUrl(value) {
  return SAFE_URL.test(String(value || "").trim());
}

function allowedAttribute(name) {
  if (name.startsWith("on")) return false;
  if (PREFIX_ATTRS.test(name)) return true;
  return ALLOWED_ATTRS.has(name);
}

function scrubAttributes(element) {
  Array.prototype.slice.call(element.attributes).forEach((attr) => {
    const name = attr.name.toLowerCase();
    if (URL_ATTRS.has(name)) {
      if (!safeUrl(attr.value)) element.removeAttributeNode(attr);
      return;
    }
    if (!allowedAttribute(name)) {
      element.removeAttributeNode(attr);
      return;
    }
    if (name === "style") {
      const cleaned = sanitizeCss(attr.value);
      if (cleaned.trim()) element.setAttribute("style", cleaned);
      else element.removeAttributeNode(attr);
    }
  });
}

/* Depth-first, children snapshotted before the walk so removals cannot make
   the traversal skip a sibling. */
function scrub(node) {
  Array.prototype.slice.call(node.childNodes).forEach((child) => {
    if (child.nodeType === Node.COMMENT_NODE || child.nodeType === Node.PROCESSING_INSTRUCTION_NODE) {
      child.remove();
      return;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) return;
    const name = String(child.localName || "").toLowerCase();
    if (child.namespaceURI !== SVG_NS || !ALLOWED_ELEMENTS.has(name)) {
      child.remove();
      return;
    }
    scrubAttributes(child);
    if (name === "style") {
      child.textContent = sanitizeCss(child.textContent);
      return;
    }
    scrub(child);
  });
}

/* Parse untrusted SVG text and hand back a sanitised element, or null when the
   text is not usable SVG at all. DOMParser does not run scripts, so nothing in
   the input executes before the scrub. */
function sanitizeSvg(markup) {
  const doc = new DOMParser().parseFromString(String(markup || ""), "image/svg+xml");
  const root = doc.documentElement;
  if (!root || root.namespaceURI !== SVG_NS || root.localName !== "svg") return null;
  if (doc.getElementsByTagName("parsererror").length) return null;
  scrubAttributes(root);
  scrub(root);
  return root;
}

/* Serialise a sanitised element back to text — the export path re-uses this so
   what a user downloads is exactly what was on screen. */
function serializeSvg(element) {
  return element ? new XMLSerializer().serializeToString(element) : "";
}

window.SFSanitize = {
  sanitizeSvg: sanitizeSvg,
  sanitizeCss: sanitizeCss,
  serializeSvg: serializeSvg,
  ALLOWED_ELEMENTS: ALLOWED_ELEMENTS,
  ALLOWED_ATTRS: ALLOWED_ATTRS,
};

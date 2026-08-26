"use strict";

/* Shell: fetch helper, DOM helpers, the notice bar and the hash router.
   home.js and studio.js attach their entry points to window.SF.

   Every string that comes from the server or from the user is placed with
   textContent. The one exception in the whole app is the sanitised SVG the
   renderer inserts — see sanitize.js for why that one is allowed. */

const SF = (window.SF = window.SF || {});

const SKETCH_ROUTE = /^#\/sketch\/([a-z0-9-]{1,64})$/;
const STATUS_RE = /^(empty|drafted)$/;
const TYPE_RE = /^(flowchart|sequence|state|er|class|other)$/;
const SNIPPET = 120;

const noticeBar = document.getElementById("notice");
const views = {
  home: document.getElementById("view-home"),
  studio: document.getElementById("view-studio"),
};

async function request(method, path, payload) {
  const options = { method: method, headers: { Accept: "application/json" } };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const res = await fetch(path, options);
  const body = await res.json().catch(() => ({ ok: false, error: "bad response" }));
  if (!res.ok || !body.ok) {
    const err = new Error(body.error || "request failed");
    err.status = res.status;
    throw err;
  }
  return body.data;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function button(label, className, onClick) {
  const node = el("button", className || "btn", label);
  node.type = "button";
  node.addEventListener("click", onClick);
  return node;
}

/* status and diagram type both drive a colour, so both are matched against a
   whitelist before they are allowed to become a class name. */
function statusPill(status) {
  const value = String(status || "empty");
  return el("span", "pill pill-" + (STATUS_RE.test(value) ? value : "empty"), value);
}

function typeBadge(type) {
  const value = String(type || "other");
  return el("span", "badge badge-" + (TYPE_RE.test(value) ? value : "other"), value);
}

function clearNotice() {
  noticeBar.replaceChildren();
  noticeBar.className = "notice hidden";
}

function showNotice(message, variant, actionLabel, action) {
  noticeBar.replaceChildren();
  noticeBar.className = "notice notice-" + (variant || "info");
  noticeBar.appendChild(el("span", "notice-text", message));
  if (actionLabel) noticeBar.appendChild(button(actionLabel, "btn btn-small", action));
  noticeBar.appendChild(button("Dismiss", "btn btn-small", clearNotice));
}

function snippet(text) {
  const value = (text || "").trim().replace(/\s+/g, " ");
  return value.length > SNIPPET ? value.slice(0, SNIPPET) + "…" : value;
}

function debounce(fn, wait) {
  let timer = 0;
  const wrapped = function () {
    const args = arguments;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn.apply(null, args), wait);
  };
  wrapped.cancel = () => window.clearTimeout(timer);
  return wrapped;
}

Object.assign(SF, {
  request: request,
  el: el,
  button: button,
  statusPill: statusPill,
  typeBadge: typeBadge,
  showNotice: showNotice,
  clearNotice: clearNotice,
  snippet: snippet,
  debounce: debounce,
});

// -- routing ---------------------------------------------------------------
function showView(name) {
  Object.keys(views).forEach((key) => views[key].classList.toggle("hidden", key !== name));
  document.body.dataset.view = name;
}

function route() {
  const match = SKETCH_ROUTE.exec(location.hash || "#/");
  if (match) {
    showView("studio");
    SF.openStudio(match[1]);
    return;
  }
  SF.closeStudio();
  showView("home");
  SF.loadSketches();
}

SF.go = function (hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
};

window.addEventListener("hashchange", route);
// fires once home.js and studio.js have registered their entry points
window.addEventListener("DOMContentLoaded", route);

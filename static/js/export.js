"use strict";

/* Export: SVG, PNG and the mermaid source itself.

   All three read what is on screen, and the SVG path runs the rendered markup
   through SFSanitize.sanitizeSvg again on its way out. The element in the stage
   has already been through it once — running it a second time costs nothing and
   makes the guarantee structural rather than historical: a file leaving this app
   has passed the same allowlist as the pixels the user was looking at, no matter
   what touched the DOM in between.

   PNG goes through an <img> holding a data: URL and a canvas painted white
   first, so a transparent diagram does not download as black-on-black. If any
   step of that fails — an unsupported browser, a tainted canvas, a toBlob that
   returns nothing — the user gets a message and an offer of the SVG. The one
   thing that must never happen is a silent zero-byte file, so nothing is
   downloaded until there is a blob in hand. */

(function () {
  const SF = window.SF;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const PNG_TYPE = "image/png";
  const FALLBACK = { width: 900, height: 600 };
  const MAX_PIXELS = 4000;

  const menu = document.getElementById("export-menu");
  const stage = document.getElementById("render-stage");
  const editor = document.getElementById("source-editor");

  // a test-only switch, so the failure branch above can be exercised for real
  const forceFailure = /(^|[?&])pngfail=1(&|$)/.test(window.location.search);

  function slug() {
    return (SF.studio.state && SF.studio.state.slug) || "sketch";
  }

  function download(blob, name) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    menu.removeAttribute("open");
  }

  function dimensions(node) {
    const box = (node.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
    if (box.length === 4 && box[2] > 0 && box[3] > 0) {
      return { width: box[2], height: box[3] };
    }
    const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : null;
    if (rect && rect.width > 0 && rect.height > 0) {
      return { width: rect.width, height: rect.height };
    }
    return FALLBACK;
  }

  /* The sanitised, self-contained document: explicit size, explicit namespace,
     nothing that points anywhere. Null when the canvas has nothing on it. */
  function prepared() {
    const shown = stage.querySelector("svg");
    if (!shown) return null;
    const clean = window.SFSanitize.sanitizeSvg(
      window.SFSanitize.serializeSvg(shown.cloneNode(true))
    );
    if (!clean) return null;
    const size = dimensions(clean);
    clean.setAttribute("xmlns", SVG_NS);
    clean.setAttribute("width", String(Math.round(size.width)));
    clean.setAttribute("height", String(Math.round(size.height)));
    return { text: window.SFSanitize.serializeSvg(clean), size: size };
  }

  function nothingToExport() {
    SF.showNotice("Nothing to export yet — draw something on the canvas first.", "warn");
    return null;
  }

  function rasterise(text, size, scale) {
    return new Promise((resolve, reject) => {
      if (forceFailure) {
        reject(new Error("forced by ?pngfail=1"));
        return;
      }
      const image = new Image();
      image.onload = () => {
        try {
          const canvas = document.createElement("canvas");
          canvas.width = Math.min(MAX_PIXELS, Math.max(1, Math.round(size.width * scale)));
          canvas.height = Math.min(MAX_PIXELS, Math.max(1, Math.round(size.height * scale)));
          const context = canvas.getContext("2d");
          if (!context) throw new Error("this browser has no 2d canvas");
          context.fillStyle = "#ffffff";
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          canvas.toBlob((blob) => {
            if (blob && blob.size) resolve(blob);
            else reject(new Error("the canvas produced no image data"));
          }, PNG_TYPE);
        } catch (err) {
          reject(err);
        }
      };
      image.onerror = () => reject(new Error("the diagram could not be read as an image"));
      image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
    });
  }

  function exportSvg() {
    const ready = prepared();
    if (!ready) return nothingToExport();
    download(new Blob([ready.text], { type: "image/svg+xml;charset=utf-8" }), slug() + ".svg");
    return null;
  }

  async function exportPng(scale) {
    const ready = prepared();
    if (!ready) return nothingToExport();
    try {
      const blob = await rasterise(ready.text, ready.size, scale);
      download(blob, slug() + (scale > 1 ? "@2x" : "") + ".png");
    } catch (err) {
      SF.showNotice(
        "PNG export failed: " + err.message + ". The SVG download is right here and " +
          "keeps full quality — most tools take it directly.",
        "error",
        "Download SVG",
        exportSvg
      );
    }
    return null;
  }

  function exportSource() {
    const source = editor.value;
    if (!source.trim()) return nothingToExport();
    download(new Blob([source], { type: "text/plain;charset=utf-8" }), slug() + ".mmd");
    return null;
  }

  document.getElementById("export-svg").addEventListener("click", exportSvg);
  document.getElementById("export-png").addEventListener("click", () => exportPng(1));
  document.getElementById("export-png2").addEventListener("click", () => exportPng(2));
  document.getElementById("export-mmd").addEventListener("click", exportSource);

  // clicking anywhere else closes the menu, the way a menu is expected to behave
  document.addEventListener("click", (event) => {
    if (menu.hasAttribute("open") && !menu.contains(event.target)) {
      menu.removeAttribute("open");
    }
  });
})();

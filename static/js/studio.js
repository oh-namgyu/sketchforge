"use strict";

/* Studio: source editor on the left, render canvas on the right.

   The editor renders as you type (debounced) but only *saves* when asked, and
   every save carries base_version — the version the text was edited from. A
   409 means something else was confirmed first, so the save is refused rather
   than silently overwriting; history is append-only, including reverts. */

(function () {
  const SF = window.SF;
  const RENDER_DEBOUNCE = 400;
  const STARTERS = {
    flowchart: "flowchart TD\n  A[Start] --> B{Choice}\n  B -->|yes| C[Done]\n  B -->|no| A",
    sequence: "sequenceDiagram\n  Client->>Server: request\n  Server-->>Client: response",
    state: "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Busy: work\n  Busy --> Idle: done",
    er: "erDiagram\n  CUSTOMER ||--o{ ORDER : places",
    class: "classDiagram\n  class Sketch {\n    +String title\n    +save()\n  }",
    other: "flowchart LR\n  A --> B",
  };

  const titleNode = document.getElementById("studio-title");
  const typeNode = document.getElementById("studio-type");
  const statusNode = document.getElementById("studio-status");
  const versionSelect = document.getElementById("version-select");
  const revertButton = document.getElementById("studio-revert");
  const saveButton = document.getElementById("studio-save");
  const starterButton = document.getElementById("studio-starter");
  const editor = document.getElementById("source-editor");
  const editorMeta = document.getElementById("editor-meta");
  const diffView = document.getElementById("diff-view");
  const paneTitle = document.getElementById("source-pane-title");
  const errorPanel = document.getElementById("render-error");
  const errorText = document.getElementById("render-error-text");
  const canvasNode = document.getElementById("render-canvas");
  const stageNode = document.getElementById("render-stage");
  const zoomLabel = document.getElementById("zoom-label");

  const state = { slug: "", sketch: null, baseVersion: 0, viewing: 0 };

  const canvas = window.SFRender.createCanvas({
    container: canvasNode,
    stage: stageNode,
    onView: (view) => {
      zoomLabel.textContent = Math.round(view.zoom * 100) + "%";
    },
  });

  document.getElementById("zoom-in").addEventListener("click", canvas.zoomIn);
  document.getElementById("zoom-out").addEventListener("click", canvas.zoomOut);
  document.getElementById("zoom-reset").addEventListener("click", canvas.reset);

  // -- render ---------------------------------------------------------------
  function showError(message) {
    errorText.textContent = message;
    errorPanel.classList.remove("hidden");
    canvasNode.classList.add("is-stale");
  }

  function clearError() {
    errorPanel.classList.add("hidden");
    errorText.textContent = "";
    canvasNode.classList.remove("is-stale");
  }

  let renderToken = 0;

  /* Render any source, not only the editor's: the diff preview points this at
     the proposal, which goes through the same parse-sanitise-insert path. */
  async function renderSource(source) {
    const token = (renderToken += 1);
    if (!source.trim()) {
      canvas.clear();
      clearError();
      canvasNode.classList.add("is-empty");
      return;
    }
    canvasNode.classList.remove("is-empty");
    try {
      const element = await window.SFRender.toSvgElement(source);
      if (token !== renderToken) return;
      canvas.show(element);
      clearError();
    } catch (err) {
      if (token !== renderToken) return;
      showError(window.SFRender.messageOf(err));
    }
  }

  function renderNow() {
    return renderSource(editor.value);
  }

  /* Diff mode swaps the editor for the diff rows; the canvas keeps rendering,
     but the proposal rather than the text on the left. */
  function setDiffMode(on) {
    editor.classList.toggle("hidden", on);
    diffView.classList.toggle("hidden", !on);
    starterButton.classList.toggle("hidden", on);
    paneTitle.textContent = on ? "Proposed change" : "Source";
    // while a proposal is on the table the version controls are out of reach:
    // accept or reject is the only way forward, which keeps base_version honest
    saveButton.disabled = true;
    revertButton.disabled = true;
    versionSelect.disabled = on;
    if (on) return;
    diffView.replaceChildren();
    fillVersions();
    markDirty();
  }

  const scheduleRender = SF.debounce(renderNow, RENDER_DEBOUNCE);

  function updateEditorMeta() {
    const lines = editor.value ? editor.value.split("\n").length : 0;
    editorMeta.textContent = lines + " lines · " + editor.value.length + " chars";
  }

  editor.addEventListener("input", () => {
    updateEditorMeta();
    markDirty();
    scheduleRender();
  });

  // -- state ----------------------------------------------------------------
  function markDirty() {
    const saved = versionSource(state.baseVersion);
    const dirty = editor.value !== saved;
    saveButton.disabled = !dirty || !editor.value.trim() || Boolean(state.sketch && state.sketch.read_only);
    statusNode.textContent = dirty ? "unsaved" : "saved";
    statusNode.className = "pill " + (dirty ? "pill-empty" : "pill-drafted");
  }

  function versionSource(n) {
    const versions = (state.sketch && state.sketch.versions) || [];
    const found = versions.filter((version) => version.n === n)[0];
    return found ? found.source : "";
  }

  function fillVersions() {
    const versions = (state.sketch && state.sketch.versions) || [];
    versionSelect.replaceChildren();
    versionSelect.disabled = versions.length === 0;
    if (!versions.length) versionSelect.appendChild(SF.el("option", null, "no versions yet"));
    versions.forEach((version) => {
      const option = SF.el("option", null, "v" + version.n + " · " + version.instruction);
      option.value = String(version.n);
      versionSelect.appendChild(option);
    });
    if (versions.length) versionSelect.value = String(state.viewing);
    updateRevertButton();
  }

  function updateRevertButton() {
    const current = (state.sketch && state.sketch.current) || 0;
    revertButton.disabled =
      !current || state.viewing === current || Boolean(state.sketch && state.sketch.read_only);
    revertButton.textContent = state.viewing ? "Revert to v" + state.viewing : "Revert";
  }

  function adopt(sketch) {
    state.sketch = sketch;
    state.baseVersion = sketch.current || 0;
    state.viewing = sketch.current || 0;
    titleNode.textContent = sketch.title || "(untitled)";
    typeNode.replaceChildren(SF.typeBadge(sketch.diagram_type));
    editor.value = versionSource(state.baseVersion);
    editor.readOnly = Boolean(sketch.read_only);
    fillVersions();
    updateEditorMeta();
    markDirty();
    renderNow();
    if (sketch.read_only) {
      SF.showNotice("This sketch was written by a newer version — read only.", "warn");
    } else if (sketch.data_loss) {
      SF.showNotice("This sketch could not be read and was restarted empty.", "warn");
    }
    if (SF.afterAdopt) SF.afterAdopt(sketch);
  }

  versionSelect.addEventListener("change", () => {
    state.viewing = Number(versionSelect.value) || 0;
    editor.value = versionSource(state.viewing);
    updateEditorMeta();
    updateRevertButton();
    markDirty();
    renderNow();
  });

  // -- actions --------------------------------------------------------------
  async function save() {
    saveButton.disabled = true;
    statusNode.textContent = "saving…";
    try {
      const saved = await SF.request("POST", "/api/sketches/" + state.slug + "/versions", {
        source: editor.value,
        base_version: state.baseVersion,
      });
      const text = editor.value;
      adopt(saved);
      editor.value = text;
      markDirty();
      if (saved.dropped) {
        SF.showNotice(
          "Tidied " + saved.dropped + " old version(s) — v1 and the current version are kept.",
          "info"
        );
      }
    } catch (err) {
      if (err.status === 409) {
        SF.showNotice(
          "This sketch moved on since you started editing. Reload to see the newer version — your text is still in the editor.",
          "warn",
          "Reload",
          () => reload()
        );
      } else {
        SF.showNotice("Save failed: " + err.message, "error");
      }
      markDirty();
    }
  }

  async function revert() {
    const target = state.viewing;
    try {
      adopt(await SF.request("POST", "/api/sketches/" + state.slug + "/revert", { n: target }));
      SF.showNotice("v" + target + " is back, appended as v" + state.sketch.current + ".", "info");
    } catch (err) {
      SF.showNotice("Revert failed: " + err.message, "error");
    }
  }

  saveButton.addEventListener("click", save);
  revertButton.addEventListener("click", revert);
  starterButton.addEventListener("click", () => {
    const type = (state.sketch && state.sketch.diagram_type) || "flowchart";
    editor.value = STARTERS[type] || STARTERS.other;
    updateEditorMeta();
    markDirty();
    renderNow();
    editor.focus();
  });

  editor.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "s") {
      event.preventDefault();
      if (!saveButton.disabled) save();
    }
  });

  async function reload() {
    try {
      adopt(await SF.request("GET", "/api/sketches/" + state.slug));
      // a message parked by the home screen or by an accept survives the load
      if (!SF.flushNotice()) SF.clearNotice();
    } catch (err) {
      SF.showNotice("Could not open sketch: " + err.message, "error", "Home", () => SF.go("#/"));
    }
  }

  SF.openStudio = function (slug) {
    if (state.slug !== slug) {
      state.slug = slug;
      canvas.reset();
      canvas.clear();
      clearError();
    }
    reload();
  };

  SF.closeStudio = function () {
    scheduleRender.cancel();
    state.slug = "";
    state.sketch = null;
  };

  /* What revise.js is allowed to touch. Keeping it to one object means the diff
     flow can be read on its own without tracing the editor's internals. */
  SF.studio = {
    state: state,
    adopt: adopt,
    reload: reload,
    renderSource: renderSource,
    renderEditor: renderNow,
    setDiffMode: setDiffMode,
    savedSource: () => versionSource(state.baseVersion),
  };
})();

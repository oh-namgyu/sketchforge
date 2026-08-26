"use strict";

/* Home: the new-sketch panel and the card grid.

   Two ways in, and the blank one is never blocked. "Generate with AI" creates
   the sketch first and asks for a diagram second, so a refused or unconfigured
   model costs the user a notice, not the sketch: they land in the studio with
   an empty editor either way. */

(function () {
  const SF = window.SF;
  const TITLE_FROM_INTENT = 80;

  const grid = document.getElementById("sketch-grid");
  const emptyNote = document.getElementById("sketch-empty");
  const countBadge = document.getElementById("sketch-count");
  const titleInput = document.getElementById("f-title");
  const intentInput = document.getElementById("f-intent");
  const chipRow = document.getElementById("f-types");
  const blankButton = document.getElementById("f-blank");
  const generateButton = document.getElementById("f-generate");
  const formNote = document.getElementById("form-note");

  let chosenType = "flowchart";

  function selectType(value) {
    chosenType = value;
    Array.prototype.forEach.call(chipRow.querySelectorAll(".chip"), (chip) => {
      const active = chip.dataset.type === value;
      chip.classList.toggle("is-active", active);
      chip.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  chipRow.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip");
    if (chip) selectType(chip.dataset.type);
  });

  function askDelete(card, actions, slug) {
    actions.classList.add("hidden");
    const bar = SF.el("div", "confirm-bar");
    const restore = () => {
      bar.remove();
      actions.classList.remove("hidden");
    };
    bar.appendChild(SF.el("span", "confirm-text", "Delete this sketch?"));
    bar.appendChild(
      SF.button("Delete", "btn btn-small btn-danger", async () => {
        try {
          await SF.request("DELETE", "/api/sketches/" + slug);
          await loadSketches();
        } catch (err) {
          restore();
          SF.showNotice("Delete failed: " + err.message, "error");
        }
      })
    );
    bar.appendChild(SF.button("Cancel", "btn btn-small", restore));
    card.appendChild(bar);
  }

  async function duplicate(slug) {
    try {
      const copy = await SF.request("POST", "/api/sketches/" + slug + "/duplicate");
      SF.go("#/sketch/" + copy.slug);
    } catch (err) {
      SF.showNotice("Duplicate failed: " + err.message, "error");
    }
  }

  function sketchCard(sketch) {
    const card = SF.el("article", "card");
    card.dataset.slug = sketch.slug;

    const body = SF.el("div", "card-body");
    const title = SF.el("h3", "card-title");
    const link = SF.el("a", "link", sketch.title || "(untitled)");
    link.href = "#/sketch/" + sketch.slug;
    title.appendChild(link);
    body.appendChild(title);

    const meta = SF.el("div", "card-meta");
    meta.appendChild(SF.typeBadge(sketch.diagram_type));
    meta.appendChild(SF.statusPill(sketch.status));
    meta.appendChild(
      SF.el("span", "badge badge-plain", "v" + (sketch.version_count || 0))
    );
    if (sketch.recovered) meta.appendChild(SF.el("span", "badge badge-warn", "recovered"));
    if (sketch.data_loss) meta.appendChild(SF.el("span", "badge badge-warn", "data loss"));
    if (sketch.read_only) meta.appendChild(SF.el("span", "badge badge-warn", "read only"));
    body.appendChild(meta);
    body.appendChild(SF.el("p", "card-text", "updated " + (sketch.updated || "").slice(0, 10)));
    card.appendChild(body);

    const actions = SF.el("div", "card-actions");
    actions.appendChild(
      SF.button("Open", "btn btn-small", () => SF.go("#/sketch/" + sketch.slug))
    );
    actions.appendChild(SF.button("Duplicate", "btn btn-small", () => duplicate(sketch.slug)));
    actions.appendChild(
      SF.button("Delete", "btn btn-small btn-danger", () =>
        askDelete(card, actions, sketch.slug)
      )
    );
    card.appendChild(actions);
    return card;
  }

  function renderSketches(sketches) {
    grid.replaceChildren();
    countBadge.textContent = String(sketches.length);
    emptyNote.classList.toggle("hidden", sketches.length > 0);
    sketches.forEach((sketch) => grid.appendChild(sketchCard(sketch)));
  }

  async function loadSketches() {
    try {
      renderSketches(await SF.request("GET", "/api/sketches"));
    } catch (err) {
      grid.replaceChildren();
      emptyNote.classList.remove("hidden");
      emptyNote.textContent = "Could not load sketches: " + err.message;
    }
  }

  async function createSketch(title) {
    return SF.request("POST", "/api/sketches", {
      title: title,
      diagram_type: chosenType,
    });
  }

  function clearForm() {
    titleInput.value = "";
    intentInput.value = "";
  }

  function setBusy(on, label) {
    blankButton.disabled = on;
    generateButton.disabled = on;
    formNote.textContent = on ? label : "";
  }

  async function startBlank() {
    setBusy(true, "Creating…");
    try {
      const created = await createSketch(titleInput.value);
      clearForm();
      SF.clearNotice();
      SF.go("#/sketch/" + created.slug);
    } catch (err) {
      SF.showNotice("Could not create sketch: " + err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function generateFailure(err) {
    if (err.status === 503) {
      return [
        "Manual mode: set ANTHROPIC_API_KEY to enable AI generation. " +
          "The sketch was created — the editor works without a key.",
        "warn",
      ];
    }
    if (err.status === 502) {
      return [
        "The model did not return a usable diagram (" + err.message + "). " +
          "The sketch was created empty — write or revise it by hand.",
        "error",
      ];
    }
    return ["Generate failed: " + err.message + ". The sketch was created empty.", "warn"];
  }

  async function generate() {
    const intent = intentInput.value.trim();
    if (!intent) {
      intentInput.focus();
      return;
    }
    setBusy(true, "Drawing…");
    let slug = "";
    try {
      slug = (await createSketch(titleInput.value || intent.slice(0, TITLE_FROM_INTENT))).slug;
      await SF.request("POST", "/api/sketches/" + slug + "/generate", { intent: intent });
      SF.clearNotice();
    } catch (err) {
      if (!slug) {
        SF.showNotice("Could not create sketch: " + err.message, "error");
        setBusy(false);
        return;
      }
      SF.queueNotice.apply(null, generateFailure(err));
    } finally {
      setBusy(false);
    }
    clearForm();
    SF.go("#/sketch/" + slug);
  }

  blankButton.addEventListener("click", startBlank);
  generateButton.addEventListener("click", generate);
  titleInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (intentInput.value.trim()) generate();
      else startBlank();
    }
  });
  intentInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      generate();
    }
  });

  selectType("flowchart");
  SF.loadSketches = loadSketches;
})();

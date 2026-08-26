"use strict";

/* The revise flow: instruction in, proposal on the table, accept or reject.

   Nothing here decides what gets stored. A revise asks the server to hold a
   proposal, and accept confirms the one the server is holding — the browser
   never sends a source back, so what a user confirms is exactly what they were
   shown. Every state the studio can be in comes out of one place, afterAdopt:
   a sketch that arrives carrying a pending proposal shows the diff, whether it
   arrived from a revise call, a page reload or a second tab. */

(function () {
  const SF = window.SF;
  const studio = SF.studio;

  const input = document.getElementById("instruction-input");
  const reviseButton = document.getElementById("studio-revise");
  const reviseNote = document.getElementById("revise-note");
  const diffbar = document.getElementById("diffbar");
  const diffView = document.getElementById("diff-view");
  const diffSummary = document.getElementById("diff-summary");
  const acceptButton = document.getElementById("studio-accept");
  const rejectButton = document.getElementById("studio-reject");

  const NOTE_IDLE = "Cmd/Ctrl+Enter · 1–2 model calls on your API key";
  const NOTE_EMPTY = "Write a first diagram (or use the starter) before asking for a change.";
  const NOTE_KEYLESS = "AI is off on this instance — the editor on the left still works.";

  let showing = false;

  function path(action) {
    return "/api/sketches/" + studio.state.slug + "/" + action;
  }

  function busy(on) {
    reviseButton.disabled = on || !canRevise();
    input.disabled = on || showing;
    reviseButton.textContent = on ? "Revising…" : "Revise";
  }

  function canRevise() {
    const sketch = studio.state.sketch;
    return Boolean(sketch && sketch.current && !sketch.read_only && !showing);
  }

  function enterDiff(proposal) {
    showing = true;
    studio.setDiffMode(true);
    const counts = window.SFDiff.render(diffView, studio.savedSource(), proposal.source);
    diffSummary.textContent = "+" + counts.added + " / −" + counts.removed;
    diffbar.classList.remove("hidden");
    input.disabled = true;
    reviseButton.disabled = true;
    studio.renderSource(proposal.source);
  }

  function exitDiff() {
    if (!showing) return;
    showing = false;
    diffbar.classList.add("hidden");
    studio.setDiffMode(false);
    input.disabled = false;
    reviseButton.disabled = !canRevise();
    studio.renderEditor();
  }

  async function discard() {
    try {
      await SF.request("POST", path("reject"));
    } catch (err) {
      // best effort: the proposal is already unusable to this view
    }
  }

  /* One entry point for "what should the studio look like for this sketch". */
  SF.afterAdopt = function (sketch) {
    const proposal = sketch && sketch.pending;
    if (!proposal) {
      exitDiff();
      reviseButton.disabled = !canRevise();
      reviseNote.textContent = sketch && sketch.current ? NOTE_IDLE : NOTE_EMPTY;
      return;
    }
    if (proposal.base_version !== (sketch.current || 0)) {
      // the sketch moved on while this proposal sat there — it cannot be applied
      exitDiff();
      SF.showNotice(
        "A proposed revision was left over from an older version of this sketch, so it was discarded.",
        "warn"
      );
      discard();
      return;
    }
    enterDiff(proposal);
  };

  async function revise() {
    const instruction = input.value.trim();
    if (!instruction || !canRevise()) {
      input.focus();
      return;
    }
    busy(true);
    SF.clearNotice();
    try {
      studio.adopt(await SF.request("POST", path("revise"), { instruction: instruction }));
      input.value = "";
    } catch (err) {
      if (err.status === 503) {
        reviseNote.textContent = NOTE_KEYLESS;
        SF.showNotice(
          "Manual mode: set ANTHROPIC_API_KEY to enable AI. The editor on the left is unaffected.",
          "warn"
        );
      } else if (err.status === 502) {
        SF.showNotice(
          "The model did not return a usable diagram (" + err.message + "). " +
            "Nothing changed — try rewording, or edit the source directly.",
          "error"
        );
      } else {
        SF.showNotice("Revise failed: " + err.message, "error");
      }
    } finally {
      busy(false);
    }
  }

  async function accept() {
    acceptButton.disabled = true;
    try {
      const saved = await SF.request("POST", path("accept"));
      exitDiff();
      studio.adopt(saved);
      SF.showNotice("Accepted as v" + saved.current + ".", "info");
    } catch (err) {
      if (err.status === 409) {
        SF.queueNotice(
          "Another version was confirmed while this proposal was open, so it no longer applies — it has been discarded.",
          "warn"
        );
        await discard();
        exitDiff();
        studio.reload();
      } else {
        SF.showNotice("Accept failed: " + err.message, "error");
      }
    } finally {
      acceptButton.disabled = false;
    }
  }

  async function reject() {
    rejectButton.disabled = true;
    try {
      const cleared = await SF.request("POST", path("reject"));
      exitDiff();
      studio.adopt(cleared);
    } catch (err) {
      SF.showNotice("Reject failed: " + err.message, "error");
    } finally {
      rejectButton.disabled = false;
    }
  }

  reviseButton.addEventListener("click", revise);
  acceptButton.addEventListener("click", accept);
  rejectButton.addEventListener("click", reject);
  input.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      revise();
    }
  });
})();

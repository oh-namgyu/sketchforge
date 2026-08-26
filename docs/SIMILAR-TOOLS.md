# Similar tools — what already exists

sketchforge is **not the first** text-to-diagram tool, not the first mermaid
editor, and not the first thing that turns a sentence into a diagram with an
LLM. This file records the survey that says so, including the queries used, so
the claims in [README.md](../README.md) can be checked rather than taken on
trust.

Survey date: **2026-08-26**. Web search, then the projects' own pages.

## Queries run

| # | Query | Where the useful hits came from |
|---|-------|--------------------------------|
| 1 | `mermaid.live official mermaid chart AI text to diagram editor` | mermaid.js.org, mermaid.live, mermaid.ai, mermaideditor.io, mermaidonline.live, Diagramming AI |
| 2 | `open source self-hosted AI diagram generator LLM mermaid alternative eraser excalidraw text-to-diagram 2026` | GitHub topics `diagram-generator` / `mermaid-alternative`, Excalidraw, PlantUML, roundup articles (Dupple, Toolradar, CodePic) |
| 3 | `github open source "eraser" alternative AI system design diagram excalidraw self-hostable bring your own key repo` | GitHub topics `eraser-alternative`, AlternativeTo, Product Hunt |

Two pages were then read directly: <https://mermaid.ai/mermaid-ai> and
<https://github.com/mermaid-js/mermaid-live-editor>.

## What the survey found

### Mermaid Live Editor — <https://mermaid.live> · [source](https://github.com/mermaid-js/mermaid-live-editor)

The official editor from the mermaid project. MIT, self-hostable via a published
Docker image (`ghcr.io/mermaid-js/mermaid-live-editor`). Edit mermaid on the
left, live preview on the right, share a diagram as an encoded link, export
SVG/PNG. **No AI generation** in the open-source editor, and no server-side
document store — a diagram travels in the URL rather than living in a library on
your disk.

This is the closest thing to sketchforge's keyless core, and it is better at
being a plain mermaid editor. If a live editor is all you want, use it.

### Mermaid Chart / Mermaid AI — <https://mermaid.ai>

The commercial platform from the company behind mermaid (Mermaid Chart, founded
with Open Core Ventures, with the lead mermaid developers). It does have
prompt-to-diagram AI generation and, per its own copy, keeps context across a
conversation so a diagram can be refined by talking to it. It is **SaaS**:
sign-up required, cloud-hosted, with a free tier and paid plans. There is also a
VS Code extension.

This is the direct functional overlap — natural-language generation plus
iterative refinement. The difference is the hosting and key model, not the idea.

### Excalidraw — <https://excalidraw.com> · open source

Open source, self-hostable, and ships a built-in text-to-diagram feature; run
locally it can be pointed at an OpenAI-compatible endpoint with your own key.
Excalidraw is a freehand canvas first — the diagram is shapes, not text — so it
is a different editing model from "the mermaid source is the document".

### Diagramming AI, mermaideditor.io, mermaidonline.live and similar

A crowded field of hosted mermaid editors, most with an AI prompt box, all
free-tier SaaS. None of them are self-hosted, and their storage model is their
account, not your filesystem.

### The "open-source Eraser.io alternative" family

GitHub topics `eraser-alternative` / `ai-diagram-generator` carry at least one
Next.js project that takes plain-English system descriptions and produces
editable architecture, sequence and ERD diagrams on an Excalidraw canvas,
self-hostable with bring-your-own-key. OpenFlowKit was named in the same space
(open source, BYOK, multiple AI endpoints). The niche of "self-hosted, BYOK,
AI-drafted diagrams" is **occupied**, not empty.

### PlantUML, Graphviz, D2, Structurizr

The long-standing text-to-diagram languages. No LLM involvement of their own,
but they are the reason "describe a diagram in text and render it" is not a new
idea at all.

## Where sketchforge actually differs

Nothing here is unique on its own. The combination is what this project is:

1. **Self-hosted storage with real version history.** Every confirmed change
   appends a version to `data/sketches/<slug>/sketch.json` on your disk, with
   the instruction that produced it recorded next to it, and any version can be
   reverted (as a new version — history is append-only). The official live
   editor keeps no library; the SaaS tools keep one in their account.
2. **Revision as a reviewable proposal, not an overwrite.** A revise call puts
   the model's answer in a single `pending` slot and shows a **line diff plus a
   rendered preview** side by side. Nothing changes until Accept, and Accept
   sends no source — the server commits what it stored, and refuses (409) if a
   version landed in between.
3. **The keyless path is the core, not a degraded mode.** With no API key the
   manual editor, the live renderer, versions, revert and all three exports work
   completely; only generate and revise answer 503. The AI sits on top of a tool
   that stands without it.
4. **Rendering is treated as the security boundary it is.** The rendered SVG
   passes an **allowlist** sanitiser before it touches the DOM, the same
   function runs before export, `securityLevel: 'strict'` is on, `bindFunctions`
   is never called, and the CSP is `script-src 'self'`. Three XSS probes in the
   e2e suite fire at that path on every CI run. See [SECURITY.md](../SECURITY.md)
   — including what this does **not** prove.
5. **No account, no telemetry, no build step.** Flask plus vanilla JS plus one
   vendored mermaid bundle pinned by SHA256.

## Where the alternatives are better

Honesty cuts both ways:

- **Mermaid Live Editor** is a more polished plain editor, is maintained by the
  people who write mermaid, and its share-by-URL beats having to run a server.
- **Mermaid Chart** has collaboration, comments, a visual (drag) editor and a
  whiteboard. sketchforge is single-user with one shared token and no realtime
  anything.
- **Excalidraw** wins whenever the diagram wants to be freeform rather than a
  mermaid graph.
- Every hosted option works without installing or running anything.

Pick sketchforge if you want the diagram, its history and the key to stay on
your own machine, and if a conversational edit that you review as a diff before
it lands is worth running a small server for.

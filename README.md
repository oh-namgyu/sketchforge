# sketchforge

[![CI](https://github.com/oh-namgyu/sketchforge/actions/workflows/ci.yml/badge.svg)](https://github.com/oh-namgyu/sketchforge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

> **한글 요약** — 한 줄 의도를 쓰면 LLM이 Mermaid 다이어그램을 그려주고, "결제 실패 분기 추가해줘" 같은 말로 수정을 반복(diff 미리보기·버전 관리)한 뒤 SVG/PNG로 내보내는 셀프호스트 다이어그램 스튜디오입니다. API 키가 없어도 수동 Mermaid 편집기+실시간 렌더러로 완전히 동작합니다. *(전체 한국어 문서: [README_KOR.md](README_KOR.md))*

A self-hosted **mermaid diagram studio**.

At its core it is a plain mermaid editor that needs no API key at all: type
source on the left, watch it render on the right, save versions, revert to any
of them, export SVG, PNG or the `.mmd` source. That part is the product, and it
works offline, forever, with no account and no key.

On top of that sits the AI. Give it one line of intent — *"checkout flow with a
retry on payment failure"* — and it drafts the first version. Then keep talking
to it: **"add a branch for a failed payment"**, **"rename Cart to Basket"**. Each
instruction comes back as a **proposal**, shown as a line diff next to a rendered
preview, and nothing changes until you accept it. Every accepted change is a new
version with the instruction that produced it recorded alongside.

Everything lives in plain files on your own machine. One optional API key, no
database, no accounts, no build step.

*(README_KOR.md — [한국어 문서](README_KOR.md))*

## Not the first of its kind

Text-to-diagram tools are a crowded field and sketchforge claims **no
firsts**. The [official Mermaid Live Editor](https://mermaid.live) is a better
plain editor and is also self-hostable; [Mermaid Chart](https://mermaid.ai) does
AI generation with conversational refinement as a hosted service;
[Excalidraw](https://excalidraw.com) has text-to-diagram on a freeform canvas.
What sketchforge combines is a **self-hosted store with real version history**, a
**revise step you review as a diff before it lands**, a **keyless core** that is
the product rather than a degraded mode, and a render path treated as a security
boundary.

The full survey — search queries, what each tool does, and where the
alternatives are simply better — is in
[docs/SIMILAR-TOOLS.md](docs/SIMILAR-TOOLS.md).

## How it works

```
one line of intent
      │
      ▼
  Generate ──► v1 mermaid source            (1 API call, 2 if the first reply is malformed)
      │        …or "Start blank" and type it yourself (0 calls)
      ▼
  Render ──► parse · render · sanitise · insert   (0 — the browser does it, offline)
      │
      ▼
  Revise ──► a pending proposal              (1 API call, 2 on a retry)
      │       line diff + rendered preview, side by side
      │       Accept → new version   ·   Reject → discarded, nothing touched
      ▼
  Export ──► SVG · PNG (1× / 2×) · .mmd      (0 — all client side)
```

The manual editor and the AI are the same editor. A diagram drafted by the model
is just text in the box, so you can fix a node by hand at any point and save
that as the next version — and if the model fails three times in a row, that is
exactly what the UI tells you to do.

**Versions are append-only.** A revert does not delete history; it appends the
old source as a *new* version. History is capped at 100 per sketch, and when it
overflows the oldest middle versions are dropped while v1 and the current
version are always kept — the source of truth is the current version, the
history is a convenience.

## Screenshots

**Home** — one line of intent, a diagram-type preset, and the sketches you already have.

![sketchforge home: an intent box with diagram type chips above a grid of sketch cards](docs/shots/home.png)

**Studio, reviewing a revision** — the instruction produced a proposal: line diff on the left, the revised diagram rendered on the right, Accept/Reject in between.

![sketchforge studio in diff mode: added and removed source lines on the left, the revised flowchart rendered on the right, with an Accept and Reject bar](docs/shots/studio-diff.png)

## Quickstart

### Local (venv)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # optional — AI drafting only
python app.py
```

Open <http://127.0.0.1:6183>. The JSON API lives under `/api`.

**Without a key it is still a complete tool.** Creating sketches, editing
mermaid by hand, live rendering, saving and reverting versions and all three
exports work with no key at all — only *Generate* and *Revise* need one, and
without it those two routes return `503` and the UI says so.

Want the AI flow offline too? `SKETCHFORGE_FAKE=1 python app.py` swaps in a
deterministic offline drafter — no key, no network, no cost.

### Docker

```bash
cp .env.example .env        # fill in AUTH_TOKEN (and ANTHROPIC_API_KEY if you want AI drafting)
mkdir -p data && sudo chown 10001:10001 data
docker compose up -d
```

The container binds `0.0.0.0` inside its own network namespace, so **`AUTH_TOKEN`
is required** — the bind guard exits with code 1 without one, and compose will
refuse to start before that. Compose maps the port to `127.0.0.1:6183` on the
host, so nothing is exposed to your network until you change that line yourself.

## Configuration

All configuration is environment variables. See [.env.example](.env.example).

| Variable                 | Default           | Meaning                                                          |
|--------------------------|-------------------|------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`      | _(unset)_         | Optional. AI drafting only. Without it generate/revise → `503`; the editor, renderer, versions and exports are unaffected. |
| `AUTH_TOKEN`             | _(unset)_         | Enables token login. **Required for any non-loopback bind.**      |
| `HOST`                   | `127.0.0.1`       | Bind address.                                                     |
| `PORT`                   | `6183`            | HTTP port.                                                        |
| `SKETCHFORGE_MODEL`      | `claude-sonnet-5` | Text model used to draft and revise diagram sources.              |
| `SKETCHFORGE_DATA`       | `./data`          | Root for `sketches/<slug>/` and the deleted-sketch trash.         |
| `SKETCHFORGE_TRASH_DAYS` | `7`               | Age at which trashed sketches are purged on startup.              |
| `SKETCHFORGE_FAKE`       | _(unset)_         | `1` swaps in the deterministic offline drafter (demo/tests).       |

Per-sketch options are set in the UI: **diagram type** (flowchart, sequence,
state, ER, class — a hint for the model, not a limit on what you can type) and
the title. Limits: intent and instruction ≤ 4,000 characters, source ≤ 200 KB,
100 versions per sketch.

## Costs

**sketchforge spends your own API credits.** It is not a service and has no
billing of its own — it calls Anthropic with the key you provide, and you pay
Anthropic directly at their published rates.

| Action                                          | API calls                                                                 |
|-------------------------------------------------|---------------------------------------------------------------------------|
| **Generate** a first version from intent        | **1**, or **2** if the first reply is not usable mermaid.                  |
| **Revise** with an instruction                  | **1**, or **2** on the same retry.                                         |
| Start blank, type, render, save, revert, diff   | **0** — no model is involved.                                              |
| Accept, Reject, duplicate, delete               | **0**.                                                                     |
| Export SVG / PNG / `.mmd`                       | **0** — all three run in your browser.                                     |

The retry is capped hard at **exactly one**: a reply that fails the output check
is sent back once with the error quoted, and a second failure ends the attempt
with `502` rather than looping. So the worst case for any single action is two
calls, and output is capped at 8192 tokens per call. Rejecting a proposal costs
nothing extra; asking again does cost another call.

## Privacy

- **What is sent out:** on *Generate*, your intent line and the chosen diagram
  type. On *Revise*, your instruction and the **current diagram source**. That is
  the complete list of outbound traffic, and it only happens when you press one
  of those two buttons.
- **What is not:** there is **no telemetry, no analytics, no crash reporting and
  no update check**. sketchforge makes no other network calls of any kind. With
  no key set — or with `SKETCHFORGE_FAKE=1` — it makes none at all.
- **Where your data lives:** on your disk, under
  `data/sketches/<slug>/sketch.json` as plain JSON, including every version and
  the instruction that produced it. Deleted sketches move to the trash directory
  and are purged after 7 days. Nothing is uploaded anywhere.
- **The mermaid renderer is local.** `static/vendor/mermaid.min.js` is a
  vendored, pinned copy — no CDN, no third-party origin, and the CSP is
  `script-src 'self'`. Rendering a diagram is entirely offline.
- **API keys** are read from the server environment only. They are never written
  to disk, returned in a response, or logged.
- Anthropic applies its own data-handling policy to what you send. A diagram of
  your internal architecture is exactly the kind of thing worth thinking about
  before pressing Revise — and the manual editor is always there instead.

## Security model

sketchforge is a **single-user, self-hosted** tool.

- **Loopback by default.** `HOST=127.0.0.1` and, in Docker, the compose port map.
- **Refuses unsafe exposure.** Binding a non-loopback address without
  `AUTH_TOKEN` is a hard startup failure, not a warning.
- **Token login when exposed.** `AUTH_TOKEN` turns on a login form, a
  constant-time token comparison, and an HMAC-signed `httpOnly` /
  `SameSite=Strict` session cookie with an 8-hour lifetime. Mutating requests
  additionally pass a same-origin `Origin`/`Referer` gate.
- **Rendering is the one place markup is built from a string** — and it is
  guarded four ways: mermaid `securityLevel: 'strict'` with `htmlLabels` off and
  `bindFunctions` never called; an **allowlist** SVG sanitiser (unknown elements
  and attributes are dropped, `href` limited to `#anchor`/`http(s)`); the CSP
  `script-src 'self'` as a backstop; and three XSS probes fired at both the
  render and the export path in CI. The **same sanitiser runs before export**, so
  a downloaded file cannot differ from what was on screen.
- **The server-side syntax check is not a security control.** It is a UX
  early-reject; containment lives in the output sanitiser and the CSP. Said
  plainly because it matters: a full formal proof of the render surface is out of
  scope — see [SECURITY.md](SECURITY.md) for the honest version.
- **Untrusted diagram text.** On a revise the current source travels inside an
  explicit data block whose delimiters it cannot close, and the system prompt
  states that nothing inside it is an instruction.
- **Model failure never touches storage.** The call happens before the write, so
  a failed generate or revise leaves `sketch.json` byte for byte unchanged.
  *Accept* takes no body at all — the server commits the source it stored.
- **No TLS of its own.** Traffic is plain HTTP; a non-loopback bind prints a
  warning saying so. Put it behind a TLS-terminating reverse proxy before
  exposing it to anything.
- **No rate limiting.** A shared token is a shared spending limit.
- **Single worker by design.** Sketch writes are serialised with in-process
  locks, so multi-worker deployments are unsupported. The Docker image runs one
  process on purpose.

Full threat model: [SECURITY.md](SECURITY.md).

## Development

```bash
pip install -r requirements-dev.txt
playwright install chromium      # once, for the browser tests

python -m pytest -q              # unit suite — no network, no keys
python -m pytest e2e -q          # browser round trips against a real server

SKETCHFORGE_FAKE=1 python app.py # the whole AI flow, offline and free
```

The unit suite needs neither a network nor an API key: LLM behaviour is tested
by driving the **real** prompt contract with scripted stubs. The e2e suite starts
the real `app.py` on a temp data directory — keyless for the manual editor and
the XSS probes, `SKETCHFORGE_FAKE=1` for the generate/revise round trip — and
**skips** rather than fails when chromium is not installed.

`SKETCHFORGE_FAKE=1` is a UI and flow gate, not a drafting-quality gate: it
proves the round trip works, never that a real model draws a good diagram.

Conventions: files stay under ~300 lines, all styling lives in the global
`static/css/style.css` (no inline styles), and every dynamic string is injected
with `textContent` — the sanitised SVG is the single documented exception. See
[CONTRIBUTING.md](CONTRIBUTING.md).

### Updating the vendored mermaid bundle

The renderer is a pinned local copy, not a CDN reference, and it is updated by
hand on purpose — a mermaid bump changes the one code path that inserts markup
into the DOM.

```bash
# 1. edit MERMAID_VERSION in scripts/vendor.sh
./scripts/vendor.sh              # fetches the npm tarball, rewrites CHECKSUMS and NOTICE

# 2. re-run the probes against the new bundle — this is the point of the procedure
python -m pytest e2e/test_studio.py -q

# 3. commit static/vendor/mermaid.min.js, static/vendor/mermaid.LICENSE,
#    static/vendor/CHECKSUMS and NOTICE together
```

The version string is the script's only input, so re-running it on a clean
checkout must reproduce the same SHA256; if it does not, the upstream artifact
changed and the bump needs review. Dependabot covers pip, Actions and the Docker
base image, and deliberately does **not** watch `static/vendor/`.

## Limitations

- **Mermaid only.** There is no freeform canvas, no drag editing, no draw.io or
  Excalidraw import. The mermaid source *is* the document — which is what makes
  diffing, versioning and export deterministic, and also the reason a diagram
  mermaid cannot express is out of reach.
- **Line diffs, not structural ones.** A revision is compared line by line. On a
  large rewrite that reads as a wall of red and green; the rendered preview next
  to it is the intended remedy.
- **One proposal at a time.** `pending` is a single slot — a new revise replaces
  the previous proposal rather than queueing. There is no branching.
- **No collaboration.** Single user, one shared token, no comments, no realtime
  anything. Two browsers on one sketch are handled by optimistic concurrency
  (`409`), not merged.
- **Drafting quality is the model's.** A vague intent produces a vague diagram,
  and complex domain diagrams often still want a human editing pass. The manual
  editor exists because that is expected, not exceptional.
- **PNG export depends on the browser.** It is verified against chromium; a
  failed conversion shows an error and offers the SVG rather than downloading an
  empty file.
- **Volume caps.** 4,000 characters of intent or instruction, 200 KB of source,
  100 versions per sketch.
- **No TLS, no multi-language UI.** The interface is English.

## License

MIT — see [LICENSE](LICENSE). Third-party notices: [NOTICE](NOTICE).

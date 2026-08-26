# Security Policy

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 0.x (latest on `main`) | :white_check_mark: |
| older commits          | :x:                |

sketchforge is pre-1.0. Only the latest state of the default branch receives
fixes.

## Reporting a vulnerability

Please report security issues **privately** through
[GitHub Security Advisories](https://github.com/oh-namgyu/sketchforge/security/advisories/new)
on this repository. Do not open a public issue for a sensitive report. You can
expect an initial response within a few days.

## Threat model

sketchforge is a **single-user, self-hosted** tool. It binds `127.0.0.1` by
default, holds no user accounts, and treats the machine it runs on as trusted.

What is stored is always **text** — a mermaid source string. Storage therefore
has no execution surface: a hostile diagram sitting in `sketch.json` does
nothing. The risk exists at exactly one moment, **when that text is rendered
into SVG and inserted into the document**, and that is the boundary this
document spends most of its words on.

The other boundaries are ordinary: the network exposure of the HTTP port, and
untrusted text coming back from a language model.

## The render exception — the one place markup is built from a string

Everywhere else in this app, dynamic strings reach the DOM through
`textContent`. The renderer cannot: a diagram *is* markup. `static/js/render.js`
asks mermaid for SVG and inserts an element built from it, and that is a
deliberate, single, documented exception to the rule.

Four layers stand in front of it:

1. **`securityLevel: 'strict'`** — mermaid's own sanitiser, plus `htmlLabels`
   off so labels come out as `<text>` rather than `<foreignObject>` HTML.
   `bindFunctions` — the callback mermaid returns so a page can wire up `click`
   directives — is **never called**, so a `click A call alert()` in a source is
   inert before anything else happens to it.
2. **An allowlist sanitiser** (`static/js/sanitize.js`, `sanitizeSvg`). An
   element survives only if it is in the SVG namespace *and* its local name is
   on the list; an attribute survives only if its name is on the list (or has an
   `aria-`/`data-` prefix). Everything else is removed without being asked what
   it is: every `on*` handler, `<script>`, `<foreignObject>`, `<image>`, every
   animation element, any HTML that rode in on a label. `href`/`xlink:href` are
   the only attributes with a value policy — same-document anchors and
   `http(s)` only, so no `javascript:`, `data:` or `blob:`. CSS inside `style`
   attributes and `<style>` elements has `@import` and non-local `url()`
   references stripped. Parsing happens through `DOMParser`, which does not run
   scripts, so nothing executes before the scrub.
   **The same function runs before export**, so a downloaded file has passed the
   same allowlist as the pixels on screen — the two paths cannot disagree.
3. **Content-Security-Policy** —
   `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'`.
   If markup ever did slip past layer 2, `script-src 'self'` still blocks it
   from executing. `style-src` carries `'unsafe-inline'` because a mermaid theme
   arrives as an inline `<style>` block and style attributes; inline CSS cannot
   execute script while `script-src` stays `'self'`, and the sanitiser has
   already removed external `url()` references from every style it passes.
4. **e2e probes.** Three hostile sources — a `<script>` tag in a label, a
   `click ... call` callback, and a `<foreignObject>` with an `onerror` image —
   are fired at both the render path and the export path on every CI run, and
   asserted to neither execute nor survive.

### An allowlist is a blocklist's replacement, not a proof

The server-side check in `core/mermaid_check.py` rejects some obviously hostile
tokens. **That is a UX early-reject, not a security control**, and the module
says so at the top of the file. Mermaid's input language is large and evolving;
no keyword list can decide whether a source is safe. That is precisely why the
defence is on the *output* side.

Being honest about the ceiling: **a formal proof that the render surface is
free of script execution is out of scope for this project.** SVG is a large
specification, browsers implement it in ways that change, and the allowlist is
maintained by hand against what mermaid actually emits. What can be said is
narrower and true:

- the allowlist fails **closed** — an unknown element or attribute is dropped,
  so a future mermaid feature breaks a diagram's appearance before it breaks
  containment;
- a bypass therefore needs a way to script *through an element and attribute
  that are on the list*, and then still needs to defeat `script-src 'self'`;
- the probes prove the three known classes of attack fail today, not that no
  fourth class exists.

Treat the CSP as the backstop it is, and please report anything that gets past
layer 2 even if the CSP stopped it — that is still a bug in the sanitiser.

## Built-in hardening

- **Bind guard.** Binding a non-loopback address without `AUTH_TOKEN` is a hard
  startup failure (`SystemExit(1)`), not a warning. Misconfigured exposure is
  therefore impossible to do silently.
- **Token authentication.** With `AUTH_TOKEN` set, a login form takes the token,
  compares it with `hmac.compare_digest` (constant time), and issues a session
  cookie whose value is `HMAC-SHA256(AUTH_TOKEN, timestamp)`. The cookie is
  `httpOnly`, `SameSite=Strict`, `Secure` when the request is HTTPS, and expires
  after 8 hours. Without a token the app is in open mode — intended only for a
  loopback bind.
- **Same-origin gate.** `POST` / `PATCH` / `PUT` / `DELETE` additionally require
  an `Origin` or `Referer` whose host:port matches the request host. Combined
  with `SameSite=Strict` this covers CSRF and DNS rebinding.
- **Security headers.** `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: same-origin` accompany the CSP above.
- **Slug guard.** Sketch slugs must match `^[a-z0-9-]{1,64}$`, and the resolved
  path is re-checked to be a direct child of the sketches directory before any
  read or write. Path traversal is rejected with `400`.
- **No outbound fetching except the model.** The server contacts exactly one
  host, the Anthropic API, and only when you press Generate or Revise. There is
  no URL a user can make the server open, no upload, no image fetching — so
  there is no SSRF surface.
- **Prompt-injection boundary.** On a revise, the current diagram is
  third-party text: it may have been pasted from anywhere. It travels inside an
  explicit `<current-source>` data block, the system prompt states in the
  imperative that nothing inside that block is an instruction, and the only
  instruction the model may follow is the `INSTRUCTION:` line outside the block.
  A fixture whose node labels try to give the model orders is part of the test
  suite, and the offline drafter refuses outright if the injection rule is ever
  removed from the system prompt — so the shield cannot be deleted without a
  test going red.
- **Model output is never trusted.** A reply is stripped of a code fence,
  checked, and — if it fails — sent back **exactly once** with the error quoted.
  A second failure ends the attempt: the caller gets `502` with a raw preview
  rendered as plain text in a `<pre>`, never as a diagram, and the stored sketch
  is not touched.
- **Accept takes no body.** Confirming a revision commits the source the
  *server* stored in `pending`, so nothing a browser holds can be swapped in on
  the way. If a version landed since the proposal was made, accept returns
  `409` and leaves the proposal in place.
- **Optimistic concurrency on manual saves.** A manual save must name the
  `base_version` it started from; a mismatch is `409` rather than a silent
  overwrite.
- **Atomic writes.** `sketch.json` is written to a temp file and `os.replace`d,
  with the previous good copy rotated to `sketch.json.bak`. Model calls happen
  entirely before the write, so a failed generate or revise leaves the file byte
  for byte unchanged. If both the file and its backup are unreadable, the
  damaged bytes are preserved as `sketch.json.corrupt-<ts>` and the caller is
  told data was lost — a sketch is never silently emptied. Deletes are an atomic
  rename into the trash directory, purged after 7 days.
- **Schema forward-guard.** A document written by a newer schema version is
  loaded read-only rather than overwritten.
- **Secret handling.** The API key is read from the server environment only. It
  is never persisted, echoed in a response, or logged.

## Supply chain — the vendored mermaid bundle

`static/vendor/mermaid.min.js` is a **pinned copy** of a specific mermaid
release, not a CDN reference. The CSP is `script-src 'self'`, so nothing is
loaded from a third-party origin at runtime and there is no CDN to compromise.

- The version, the exact npm tarball URL, the license and the **SHA256** of both
  the bundle and its license file are recorded in [NOTICE](NOTICE) and
  `static/vendor/CHECKSUMS`.
- `scripts/vendor.sh` is the only supported way to change it: the version string
  is the single input, the artifact comes from the public npm registry, and the
  checksums and NOTICE are regenerated from what was actually downloaded.
  Re-running it on a clean checkout must reproduce the same hash; if it does
  not, the upstream artifact changed and the bump needs review, not a merge.
- **Dependabot deliberately does not watch it.** A mermaid bump changes the one
  code path that inserts markup into the DOM, so it is a manual update gated on
  re-running the XSS probe e2e (`e2e/test_studio.py`) with the new bundle. The
  bundle, `CHECKSUMS` and `NOTICE` are committed together.

Dependabot does cover pip, GitHub Actions and the Docker base image weekly, with
patch/minor auto-merge and majors left manual.

## Plaintext transport — read before exposing

**sketchforge does not terminate TLS.** Traffic, including the token you type
into the login form, is plain HTTP. A non-loopback bind prints a warning saying
so.

If you expose it beyond loopback, putting it behind a **TLS-terminating reverse
proxy** (nginx, Caddy, Traefik) is a requirement, not a suggestion. The
`SameSite=Strict` cookie is also only marked `Secure` when the request arrives
over HTTPS, which requires that proxy.

## Known limitations

- **No rate limiting.** Nothing throttles login attempts, generate or revise. A
  leaked token is both an access problem and a **spending** problem, since every
  AI action bills your own API key. Rate limit at the reverse proxy if the
  instance is reachable by anyone else.
- **One shared token.** There are no accounts and no per-user separation;
  everyone who has `AUTH_TOKEN` has full access to every sketch.
- **Single process.** Storage safety relies on in-process locks, so running
  multiple workers (gunicorn, uwsgi) is unsupported and will corrupt concurrent
  writes. The Docker image runs one process on purpose.
- **Trusted local machine.** `data/` is stored unencrypted, readable by anything
  running as the same user. Your intents and instructions are part of that data.
- **Browser coverage.** The render and export paths are verified against
  chromium in CI. Other engines are expected to work but are not gated.
- **The render surface is defended, not proven.** See the honest statement
  above.

## Not a security boundary

The server-side `core/mermaid_check.py` smoke check and the client-side
`mermaid.parse()` gate are **syntax and UX controls**, not security controls.
Neither decides whether a source is safe; the output sanitiser and the CSP do.
Do not add a feature that relies on either of them for containment.

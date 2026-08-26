# Contributing to sketchforge

Thanks for your interest! sketchforge is a small, dependency-light project and
contributions are welcome.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium         # once, for the browser tests

python -m pytest -q                 # unit suite (no network, no API key)
python -m pytest e2e -q             # browser round trips against a real server

python app.py                       # keyless: the manual editor and renderer
SKETCHFORGE_FAKE=1 python app.py    # + a deterministic offline drafter
```

Open <http://127.0.0.1:6183>.

Most of the app needs no key at all — the manual editor, the live renderer,
versions, revert and every export are the keyless core. `SKETCHFORGE_FAKE=1`
adds an offline drafter so the generate/revise/diff/accept flow can be developed
without a key, a network or any spending. The e2e suite skips itself rather than
failing when chromium is not installed.

## Conventions

- **Keep files small.** A source file over ~300 lines, or a function over ~50,
  wants splitting.
- **No inline styles.** Every style is a reusable class in the global
  `static/css/style.css` — no `style="..."` attributes, no per-component
  stylesheets.
- **`textContent` only.** The renderer's SVG insertion is the *single* allowed
  exception, and it goes through `SFSanitize.sanitizeSvg` first. Anywhere else,
  `innerHTML` with user- or model-derived data is a stored-XSS bug.
- **Do not weaken the render path.** If a change touches `static/js/render.js`,
  `static/js/sanitize.js`, `static/js/export.js` or the CSP in `app.py`, say so
  in the PR and make sure the XSS probes in `e2e/test_studio.py` still pass. New
  elements or attributes go on the allowlist explicitly, one at a time, with a
  reason — never by relaxing the check. Read [SECURITY.md](SECURITY.md) first.
- **The server check is not a security control.** `core/mermaid_check.py` is a
  UX early-reject. Do not build anything that depends on it for containment.
- **The unit suite never touches the network.** LLM behaviour is tested by
  driving the real prompt contract with scripted stubs. A test that would open a
  socket does not belong in `tests/`.
- **Never trust a model reply.** It is stripped, checked, retried exactly once,
  and never allowed to touch storage until it passes. Failures must leave
  `sketch.json` byte for byte unchanged — there are tests for that.
- **Keep the injection shield intact.** The current source travels in a
  `<current-source>` block and the system prompt says nothing inside it is an
  instruction. The offline drafter refuses to work if that rule disappears, on
  purpose.
- **Keep dependencies minimal.** Flask and the Anthropic SDK, which is imported
  lazily so the tests never need it. The only front-end dependency is the
  vendored mermaid bundle.
- **Vendored mermaid is updated by hand.** Change the version in
  `scripts/vendor.sh`, run it, re-run the XSS probe e2e, and commit the bundle,
  `static/vendor/CHECKSUMS` and `NOTICE` together. Dependabot does not do this
  for you, deliberately.
- **Type hints** on new functions.
- **Add or update tests** in `tests/` (or `e2e/`) for every behaviour change.

## The UI is English

All interface strings, including status and error text, are English. Korean
belongs in `README_KOR.md` — not in the app.

## Pull requests

Keep PRs focused on one change. Describe what changed and how you verified it,
and make sure `python -m pytest -q` is green before opening one. CI runs the unit
suite on Python 3.10 and 3.12, the e2e suite on 3.12, and a Docker build smoke
test.

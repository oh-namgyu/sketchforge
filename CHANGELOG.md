# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-16

### Changed

- The Docker image is built on `python:3.14-slim` (was `3.12-slim`).
- Minimum dependency versions raised: `anthropic>=1.13.0`; for development,
  `pytest-playwright>=0.10.0`.

## [0.1.0] - 2026-08-26

Initial public release.

### Added

- A self-hosted Flask mermaid studio whose keyless core is a manual editor
  with live in-browser rendering, saved versions, revert and export to SVG,
  PNG (1x or 2x) or `.mmd`, all without an API key.
- Append-only version history (a revert appends a new version), capped at 100
  per sketch with v1 and the current version always kept.
- AI drafting through the Anthropic API when `ANTHROPIC_API_KEY` is set:
  generate a first version from one line of intent and a diagram-type hint,
  then revise with instructions. Each revision is a pending proposal shown as
  a line diff next to a rendered preview, and nothing changes until it is
  accepted. A malformed reply is retried exactly once.
- Render path hardening: mermaid `securityLevel: 'strict'`, an allowlist SVG
  sanitiser applied to both display and export, a
  `script-src 'self'` Content Security Policy, and XSS probes in the e2e
  suite.
- A vendored, pinned mermaid 11.17.2 bundle with checksum and NOTICE, updated
  through `scripts/vendor.sh`; no CDN.
- Plain-file storage under `data/sketches/<slug>/sketch.json`, with deleted
  sketches moved to a trash folder and purged after 7 days.
- Security defaults: loopback bind, a hard startup failure for a
  non-loopback bind without `AUTH_TOKEN`, token login with an HMAC-signed
  session cookie and an `Origin`/`Referer` gate on writes.
- `SKETCHFORGE_FAKE=1` for a deterministic offline drafter.
- Dockerfile and `compose.yml`.

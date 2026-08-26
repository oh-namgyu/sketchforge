#!/usr/bin/env bash
# Vendor the pinned mermaid build into static/vendor/.
#
# Reproducible by construction: the version below is the only input, the
# tarball comes from the public npm registry, and the resulting bundle is
# hashed into static/vendor/CHECKSUMS. Re-running this script on a clean
# checkout must reproduce the same hash — if it does not, the upstream
# artifact changed and the bump has to be reviewed, not merged.
#
# Updating mermaid:
#   1. change MERMAID_VERSION below
#   2. run this script
#   3. re-run the XSS probe e2e (e2e/test_studio.py) — the render path is the
#      one place sketchforge inserts markup, so a library bump re-opens it
#   4. commit the bundle, CHECKSUMS and NOTICE together
#
# Dependabot does not watch this file: vendored assets are updated by hand
# on purpose, so a bump always comes with the probe re-run above.

set -euo pipefail

MERMAID_VERSION="11.17.2"
REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$ROOT/static/vendor"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

TARBALL_URL="$REGISTRY/mermaid/-/mermaid-$MERMAID_VERSION.tgz"
echo "[vendor] fetching $TARBALL_URL"
curl -fsSL -o "$WORK/mermaid.tgz" "$TARBALL_URL"

echo "[vendor] extracting dist/mermaid.min.js"
tar -xzf "$WORK/mermaid.tgz" -C "$WORK" package/dist/mermaid.min.js package/LICENSE

mkdir -p "$VENDOR_DIR"
cp "$WORK/package/dist/mermaid.min.js" "$VENDOR_DIR/mermaid.min.js"
cp "$WORK/package/LICENSE" "$VENDOR_DIR/mermaid.LICENSE"

hash_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

BUNDLE_SHA="$(hash_of "$VENDOR_DIR/mermaid.min.js")"
LICENSE_SHA="$(hash_of "$VENDOR_DIR/mermaid.LICENSE")"

cat > "$VENDOR_DIR/CHECKSUMS" <<EOF
# sha256 of the vendored artifacts — regenerate with scripts/vendor.sh
# mermaid $MERMAID_VERSION (npm tarball $TARBALL_URL)
$BUNDLE_SHA  mermaid.min.js
$LICENSE_SHA  mermaid.LICENSE
EOF

cat > "$ROOT/NOTICE" <<EOF
sketchforge bundles third-party code in static/vendor/.
Nothing here is loaded from a CDN: the Content-Security-Policy is
"default-src 'self'; script-src 'self'", so every script is served locally.

------------------------------------------------------------------------
mermaid $MERMAID_VERSION
------------------------------------------------------------------------
License:  MIT
Homepage: https://mermaid.js.org/
Source:   $TARBALL_URL
File:     static/vendor/mermaid.min.js  (dist/mermaid.min.js, UMD bundle)
sha256:   $BUNDLE_SHA
Full license text: static/vendor/mermaid.LICENSE

Vendored, not tracked by dependabot. Update with scripts/vendor.sh and
re-run the XSS probe e2e before committing (see the header of that script).
EOF

echo "[vendor] mermaid $MERMAID_VERSION"
echo "[vendor] sha256 $BUNDLE_SHA"
echo "[vendor] wrote static/vendor/CHECKSUMS and NOTICE"

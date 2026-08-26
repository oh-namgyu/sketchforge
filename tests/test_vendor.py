"""The vendored bundle is part of the source tree, so it is checked like one.

scripts/vendor.sh is the only way this file should ever change; these tests make
a hand-edited or half-copied bundle fail the suite instead of the browser.
"""

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "static" / "vendor"
CHECKSUMS = VENDOR / "CHECKSUMS"
NOTICE = ROOT / "NOTICE"
LINE_RE = re.compile(r"^([0-9a-f]{64})\s+(\S+)$")


def checksum_entries() -> list[tuple[str, str]]:
    entries = []
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        match = LINE_RE.match(line.strip())
        if match:
            entries.append((match.group(1), match.group(2)))
    return entries


def test_checksums_file_lists_the_bundle() -> None:
    names = [name for _digest, name in checksum_entries()]
    assert "mermaid.min.js" in names and "mermaid.LICENSE" in names


@pytest.mark.parametrize("digest,name", checksum_entries())
def test_vendored_file_matches_its_checksum(digest: str, name: str) -> None:
    path = VENDOR / name
    assert path.is_file(), f"{name} is listed in CHECKSUMS but missing"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_bundle_is_self_contained() -> None:
    """The UMD build must not reach out for lazy chunks — CSP forbids it anyway."""
    text = (VENDOR / "mermaid.min.js").read_text(encoding="utf-8", errors="ignore")
    assert len(text) > 1_000_000
    assert "import(" not in text


def test_notice_names_the_pinned_version_and_license() -> None:
    notice = NOTICE.read_text(encoding="utf-8")
    version = re.search(r"^mermaid (\d+\.\d+\.\d+)$", notice, re.MULTILINE)
    assert version, "NOTICE must name the pinned mermaid version"
    assert "MIT" in notice
    assert version.group(1) in CHECKSUMS.read_text(encoding="utf-8")


def test_vendor_script_pins_the_same_version() -> None:
    script = (ROOT / "scripts" / "vendor.sh").read_text(encoding="utf-8")
    pinned = re.search(r'MERMAID_VERSION="([^"]+)"', script)
    assert pinned, "vendor.sh must pin an exact version"
    assert pinned.group(1) in NOTICE.read_text(encoding="utf-8")

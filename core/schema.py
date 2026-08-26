"""sketch.json v1: the document shape, its validation and the version policy.

Kept apart from storage.py so the contract can be read (and tested) without
any filesystem concerns.

The stored document is always *text* — a mermaid source string. Storage has no
execution surface; the risk lives at render time and is handled by the output
sanitiser in static/js/sanitize.js plus the CSP. See SECURITY notes in the API.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
SLUG_RE = re.compile(r"^[a-z0-9-]{1,64}$")

MAX_TITLE = 200
MAX_SOURCE = 200_000  # 200 KB of mermaid text
MAX_INSTRUCTION = 4_000
MAX_VERSIONS = 100

VALID_TYPES = ("flowchart", "sequence", "state", "er", "class", "other")
VALID_STATUS = ("empty", "drafted")
DEFAULT_TYPE = "flowchart"

# transient load-time markers; they describe the read, not the stored sketch
VOLATILE_FIELDS = ("recovered", "data_loss", "read_only")
SUMMARY_FIELDS = (
    "schema",
    "slug",
    "title",
    "diagram_type",
    "status",
    "created",
    "updated",
    "current",
)


class StorageError(Exception):
    """Base error for storage operations."""


class SketchNotFound(StorageError):
    """Requested sketch does not exist."""


class VersionConflict(StorageError):
    """Optimistic concurrency check failed: someone else committed first."""


class VersionNotFound(StorageError):
    """Requested version number is not in the history."""


class ReadOnlySketch(StorageError):
    """The document was written by a newer schema; refuse to overwrite it."""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(text: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")[:64].strip("-")
    return slug or "sketch"


def validate_slug(slug: Any) -> str:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError("invalid slug")
    return slug


def require_text(value: Any, field: str, limit: int, allow_empty: bool = False) -> str:
    if value is None and allow_empty:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise ValueError(f"{field} is required")
    if len(value) > limit:
        raise ValueError(f"{field} is too long (max {limit})")
    return value


def normalise_type(value: Any) -> str:
    if value is None or value == "":
        return DEFAULT_TYPE
    if not isinstance(value, str) or value not in VALID_TYPES:
        raise ValueError("diagram_type must be any of: " + ", ".join(VALID_TYPES))
    return value


def normalise_title(value: Any) -> str:
    title = require_text(value, "title", MAX_TITLE, allow_empty=True)
    return title or "Untitled sketch"


def new_sketch(slug: str, title: str, diagram_type: str) -> Dict[str, Any]:
    """A sketch.json v1 document with no versions yet (a blank start)."""
    now = utcnow()
    return {
        "schema": SCHEMA_VERSION,
        "slug": slug,
        "title": title,
        "diagram_type": diagram_type,
        "status": "empty",
        "created": now,
        "updated": now,
        "versions": [],
        "current": 0,
        "pending": None,
    }


def version_entry(n: int, source: str, instruction: str) -> Dict[str, Any]:
    return {"n": n, "source": source, "instruction": instruction, "created": utcnow()}


def find_version(sketch: Dict[str, Any], n: Any) -> Dict[str, Any]:
    if isinstance(n, str) and n.isdigit():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int):
        raise ValueError("version must be an integer")
    for version in sketch.get("versions") or []:
        if version.get("n") == n:
            return version
    raise VersionNotFound(f"no version {n}")


def current_source(sketch: Dict[str, Any]) -> str:
    """Source of the current version, or "" for a sketch that has none yet."""
    if not sketch.get("current"):
        return ""
    return str(find_version(sketch, sketch["current"]).get("source") or "")


def append_version(
    sketch: Dict[str, Any], source: str, instruction: str
) -> Tuple[Dict[str, Any], int]:
    """Append a confirmed source as the next version. Returns (entry, dropped).

    History is append-only: a revert is a *new* version carrying an old source,
    never a truncation. The cap keeps a long-lived sketch bounded — history is a
    convenience, the source of truth is the current version — so on overflow the
    oldest middle versions are dropped while v1 (the origin) and the current
    version are always kept.
    """
    source = require_text(source, "source", MAX_SOURCE)
    instruction = require_text(instruction, "instruction", MAX_INSTRUCTION, allow_empty=True)
    versions: List[Dict[str, Any]] = sketch.setdefault("versions", [])
    number = max((v.get("n") or 0) for v in versions) + 1 if versions else 1
    entry = version_entry(number, source, instruction)
    versions.append(entry)
    sketch["current"] = number
    sketch["status"] = "drafted"
    dropped = _enforce_cap(versions, number)
    return entry, dropped


def _enforce_cap(versions: List[Dict[str, Any]], current: int) -> int:
    """Drop oldest versions past the cap, never v1 and never the current one."""
    dropped = 0
    while len(versions) > MAX_VERSIONS:
        victim = next(
            (v for v in versions if v.get("n") not in (1, current)),
            None,
        )
        if victim is None:  # pragma: no cover - needs a cap below 2
            break
        versions.remove(victim)
        dropped += 1
    return dropped


def summarise(sketch: Dict[str, Any]) -> Dict[str, Any]:
    """Card-sized view: no sources, but what the home grid needs to draw a card."""
    summary = {key: sketch.get(key) for key in SUMMARY_FIELDS}
    summary["version_count"] = len(sketch.get("versions") or [])
    summary["has_pending"] = bool(sketch.get("pending"))
    for field in VOLATILE_FIELDS:
        if sketch.get(field):
            summary[field] = True
    return summary


def check_schema(sketch: Any) -> Dict[str, Any]:
    """Version hook: a sketch written by a newer release is read-only, not junk."""
    if not isinstance(sketch, dict):
        raise StorageError("sketch is not an object")
    version = sketch.get("schema")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        sketch["read_only"] = True
    return sketch


def guard_writable(sketch: Dict[str, Any]) -> None:
    if sketch.get("read_only"):
        raise ReadOnlySketch(sketch.get("slug") or "sketch")


def normalise_pending(source: str, instruction: str, base_version: int) -> Dict[str, Any]:
    """The single pending slot: a proposal waiting for accept/reject."""
    return {
        "source": require_text(source, "source", MAX_SOURCE),
        "instruction": require_text(instruction, "instruction", MAX_INSTRUCTION, allow_empty=True),
        "base_version": int(base_version),
    }


def require_base_version(sketch: Dict[str, Any], base_version: Any) -> int:
    """Optimistic concurrency: the client must name the version it edited from."""
    if isinstance(base_version, str) and base_version.isdigit():
        base_version = int(base_version)
    if isinstance(base_version, bool) or not isinstance(base_version, int):
        raise ValueError("base_version is required")
    current: Optional[int] = sketch.get("current") or 0
    if base_version != current:
        raise VersionConflict(
            f"sketch moved on: base_version {base_version}, current {current}"
        )
    return base_version

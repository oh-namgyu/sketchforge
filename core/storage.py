"""Filesystem storage for sketches: atomic writes, per-slug locks, trash.

One sketch is one directory: data/sketches/<slug>/sketch.json. Every write goes
through a temp file plus os.replace, and the previous file is rotated to
sketch.json.bak so a torn write is always recoverable. When both copies are
unreadable the damaged bytes are preserved next to a fresh document — losing a
sketch is acceptable, losing it silently is not.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schema import (
    MAX_TITLE,
    SLUG_RE,
    SketchNotFound,
    StorageError,
    append_version,
    check_schema,
    current_source,
    find_version,
    guard_writable,
    new_sketch,
    normalise_title,
    normalise_type,
    require_text,
    slugify,
    summarise,
    utcnow,
    validate_slug,
    VOLATILE_FIELDS,
)

_locks: Dict[str, "threading.RLock"] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str):
    """Reentrant: a mutation already holding the lock may trigger a recovery write."""
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


class Storage:
    """All sketch persistence. One instance per app; data_dir is the root."""

    def __init__(self, data_dir: os.PathLike[str] | str) -> None:
        self.root = Path(data_dir).resolve()
        self.sketches_dir = self.root / "sketches"
        self.trash_dir = self.root / ".trash"
        self.sketches_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    # -- paths -----------------------------------------------------------
    def sketch_dir(self, slug: str) -> Path:
        validate_slug(slug)
        path = (self.sketches_dir / slug).resolve()
        if path != self.sketches_dir / slug or self.sketches_dir not in path.parents:
            raise ValueError("invalid slug")
        return path

    def sketch_file(self, slug: str) -> Path:
        return self.sketch_dir(slug) / "sketch.json"

    def _lock(self, slug: str):
        return _lock_for(f"{self.root}::{slug}")

    def lock(self, slug: str):
        """The sketch's own lock, for callers whose operation spans several steps."""
        validate_slug(slug)
        return self._lock(slug)

    # -- read ------------------------------------------------------------
    def exists(self, slug: str) -> bool:
        return self.sketch_file(slug).is_file()

    def load_sketch(self, slug: str) -> Dict[str, Any]:
        path = self.sketch_file(slug)
        backup = path.with_suffix(".json.bak")
        try:
            return check_schema(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            data = self._load_backup(backup)
            if data is None:
                raise SketchNotFound(slug)
            return check_schema(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = self._load_backup(backup)
            if data is not None:
                return check_schema(data)
            return self._restart_empty(slug, path)

    @staticmethod
    def _load_backup(backup: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        data["recovered"] = True
        return data

    def _restart_empty(self, slug: str, path: Path) -> Dict[str, Any]:
        """Both copies are unreadable: keep the damaged bytes, restart empty."""
        keep = path.with_name(f"sketch.json.corrupt-{int(time.time())}")
        while keep.exists():
            keep = keep.with_name(f"{keep.name}x")
        os.replace(path, keep)
        sketch = new_sketch(slug, slug, "flowchart")
        with self._lock(slug):
            self._write_sketch(slug, sketch)
        sketch["data_loss"] = True
        return sketch

    def list_sketches(self) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        for entry in sorted(self.sketches_dir.iterdir()):
            if not entry.is_dir() or not SLUG_RE.match(entry.name):
                continue
            try:
                sketch = self.load_sketch(entry.name)
            except StorageError:
                continue
            summaries.append(summarise(sketch))
        summaries.sort(key=lambda item: item.get("created") or "", reverse=True)
        return summaries

    # -- write -----------------------------------------------------------
    def _write_sketch(self, slug: str, sketch: Dict[str, Any]) -> None:
        path = self.sketch_file(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        payload = {k: v for k, v in sketch.items() if k not in VOLATILE_FIELDS}
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if path.is_file():
            os.replace(path, path.with_suffix(".json.bak"))
        os.replace(tmp, path)

    def new_slug(self, title: str) -> str:
        base = slugify(title)
        if not self.exists(base):
            return base
        for index in range(2, 1000):
            suffix = f"-{index}"
            candidate = f"{base[: 64 - len(suffix)]}{suffix}"
            if not self.exists(candidate):
                return candidate
        raise StorageError("could not allocate slug")

    def create_sketch(
        self,
        title: Any = None,
        diagram_type: Any = None,
        source: Any = None,
        instruction: str = "manual edit",
    ) -> Dict[str, Any]:
        """A new sketch. Without a source it starts blank (status "empty")."""
        title = normalise_title(title)
        require_text(title, "title", MAX_TITLE)
        kind = normalise_type(diagram_type)
        with self._lock("::new"):
            slug = self.new_slug(title)
            sketch = new_sketch(slug, title, kind)
            if source not in (None, ""):
                append_version(sketch, source, instruction)
            self._write_sketch(slug, sketch)
        return sketch

    def save_sketch(self, slug: str, sketch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock(slug):
            guard_writable(sketch)
            sketch["updated"] = utcnow()
            self._write_sketch(slug, sketch)
        return sketch

    def mutate_sketch(
        self, slug: str, change: Callable[[Dict[str, Any]], None]
    ) -> Dict[str, Any]:
        """Load, apply `change`, write — all under the sketch lock. May raise."""
        with self._lock(slug):
            sketch = self.load_sketch(slug)
            guard_writable(sketch)
            change(sketch)
            sketch["updated"] = utcnow()
            self._write_sketch(slug, sketch)
            return sketch

    def duplicate_sketch(self, slug: str) -> Dict[str, Any]:
        """Copy the current source into a brand new sketch. History is not copied."""
        origin = self.load_sketch(slug)
        return self.create_sketch(
            title=f"{origin.get('title') or slug} copy"[:MAX_TITLE],
            diagram_type=origin.get("diagram_type"),
            source=current_source(origin) or None,
            instruction=f"duplicated from {slug}",
        )

    # -- versions --------------------------------------------------------
    def commit_version(
        self, slug: str, source: str, instruction: str = "manual edit"
    ) -> Dict[str, Any]:
        """Append a version. Returns the sketch with a transient `dropped` count."""
        dropped = 0

        def change(sketch: Dict[str, Any]) -> None:
            nonlocal dropped
            _entry, dropped = append_version(sketch, source, instruction)
            sketch["pending"] = None

        sketch = self.mutate_sketch(slug, change)
        sketch = dict(sketch)
        sketch["dropped"] = dropped
        return sketch

    def revert_version(self, slug: str, n: Any) -> Dict[str, Any]:
        """"Revert to vN" appends a copy of vN as a new version — never a rewind."""
        with self._lock(slug):
            target = find_version(self.load_sketch(slug), n)
            source = str(target.get("source") or "")
            return self.commit_version(slug, source, f"revert to v{target['n']}")

    # -- delete ----------------------------------------------------------
    def delete_sketch(self, slug: str) -> str:
        with self._lock(slug):
            source = self.sketch_dir(slug)
            if not source.is_dir():
                raise SketchNotFound(slug)
            target = self.trash_dir / f"{slug}-{int(time.time())}"
            while target.exists():
                target = Path(f"{target}x")
            os.rename(source, target)
            return target.name

    def purge_trash(self, days: int = 7) -> int:
        cutoff = time.time() - days * 86400
        removed = 0
        if not self.trash_dir.is_dir():
            return 0
        for entry in self.trash_dir.iterdir():
            if not entry.is_dir() or _trash_stamp(entry) > cutoff:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
        return removed


def _trash_stamp(entry: Path) -> float:
    tail = entry.name.rsplit("-", 1)[-1]
    if tail.isdigit():
        return float(tail)
    return entry.stat().st_mtime

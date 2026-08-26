"""Version policy: append-only history, the cap, and revert-as-append."""

from pathlib import Path

import pytest

from core.schema import (
    MAX_VERSIONS,
    VersionConflict,
    VersionNotFound,
    append_version,
    current_source,
    new_sketch,
    require_base_version,
)
from core.storage import Storage


@pytest.fixture()
def store(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "data")


def src(tag: str) -> str:
    return f"flowchart TD\n  A[{tag}] --> B"


# --- append-only -----------------------------------------------------------


def test_append_numbers_from_one(store: Storage) -> None:
    slug = store.create_sketch("Numbering")["slug"]
    for index in range(1, 4):
        sketch = store.commit_version(slug, src(str(index)))
        assert sketch["current"] == index
        assert [v["n"] for v in sketch["versions"]] == list(range(1, index + 1))
    assert store.load_sketch(slug)["status"] == "drafted"


def test_append_records_instruction_and_timestamp(store: Storage) -> None:
    slug = store.create_sketch("Recorded")["slug"]
    entry = store.commit_version(slug, src("x"))["versions"][0]
    assert entry["instruction"] == "manual edit"
    assert entry["created"].endswith("+00:00")


def test_append_keeps_pending_unless_asked_to_drop_it(store: Storage) -> None:
    """An unrelated commit leaves the proposal in place — stale, and detectably
    so — while the commit that confirms it clears the slot."""
    slug = store.create_sketch("Pending")["slug"]
    store.mutate_sketch(slug, lambda s: s.update({"pending": {"source": src("p")}}))
    assert store.commit_version(slug, src("q"))["pending"] is not None
    assert store.commit_version(slug, src("r"), drop_pending=True)["pending"] is None


def test_append_rejects_empty_and_oversized_source(store: Storage) -> None:
    sketch = new_sketch("s", "S", "flowchart")
    for bad in ("", "   ", None, 5, "x" * 200_001):
        with pytest.raises(ValueError):
            append_version(sketch, bad, "manual edit")
    assert sketch["versions"] == []


# --- the cap ---------------------------------------------------------------


def test_cap_keeps_v1_and_current_and_reports_dropped() -> None:
    sketch = new_sketch("cap", "Cap", "flowchart")
    dropped_total = 0
    for index in range(1, MAX_VERSIONS + 6):
        _entry, dropped = append_version(sketch, src(str(index)), f"step {index}")
        dropped_total += dropped

    numbers = [v["n"] for v in sketch["versions"]]
    assert len(numbers) == MAX_VERSIONS
    assert dropped_total == 5
    assert numbers[0] == 1  # the origin survives
    assert sketch["current"] == MAX_VERSIONS + 5
    assert numbers[-1] == sketch["current"]  # the current version survives
    # the drops came off the front, right after v1
    assert numbers[1] == 7
    assert sketch["versions"][0]["source"] == src("1")


def test_cap_drops_one_per_append_once_full() -> None:
    sketch = new_sketch("cap2", "Cap", "flowchart")
    for index in range(MAX_VERSIONS):
        _entry, dropped = append_version(sketch, src(str(index)), "")
        assert dropped == 0
    _entry, dropped = append_version(sketch, src("over"), "")
    assert dropped == 1
    assert len(sketch["versions"]) == MAX_VERSIONS


def test_cap_surfaces_dropped_count_through_storage(store: Storage) -> None:
    slug = store.create_sketch("Overflow")["slug"]
    last = {}
    for index in range(MAX_VERSIONS + 2):
        last = store.commit_version(slug, src(str(index)))
    assert last["dropped"] == 1
    assert len(store.load_sketch(slug)["versions"]) == MAX_VERSIONS
    assert "dropped" not in store.load_sketch(slug)  # transient, never persisted


# --- revert ----------------------------------------------------------------


def test_revert_appends_a_new_version_with_old_content(store: Storage) -> None:
    slug = store.create_sketch("Revert")["slug"]
    store.commit_version(slug, src("one"))
    store.commit_version(slug, src("two"))

    reverted = store.revert_version(slug, 1)
    assert reverted["current"] == 3
    assert [v["n"] for v in reverted["versions"]] == [1, 2, 3]
    assert reverted["versions"][2]["source"] == src("one")
    assert reverted["versions"][2]["instruction"] == "revert to v1"
    # nothing was destroyed
    assert reverted["versions"][1]["source"] == src("two")
    assert current_source(reverted) == src("one")


def test_revert_accepts_a_numeric_string(store: Storage) -> None:
    slug = store.create_sketch("Revert Str")["slug"]
    store.commit_version(slug, src("one"))
    store.commit_version(slug, src("two"))
    assert store.revert_version(slug, "1")["versions"][2]["source"] == src("one")


def test_revert_to_missing_version_raises(store: Storage) -> None:
    slug = store.create_sketch("No Such")["slug"]
    store.commit_version(slug, src("one"))
    with pytest.raises(VersionNotFound):
        store.revert_version(slug, 9)
    with pytest.raises(ValueError):
        store.revert_version(slug, "abc")


# --- optimistic concurrency -----------------------------------------------


def test_require_base_version_matches_current() -> None:
    sketch = new_sketch("base", "Base", "flowchart")
    assert require_base_version(sketch, 0) == 0
    append_version(sketch, src("a"), "")
    assert require_base_version(sketch, 1) == 1
    assert require_base_version(sketch, "1") == 1


@pytest.mark.parametrize("stale", [0, 2, 99])
def test_require_base_version_rejects_stale(stale: int) -> None:
    sketch = new_sketch("base", "Base", "flowchart")
    append_version(sketch, src("a"), "")
    with pytest.raises(VersionConflict):
        require_base_version(sketch, stale)


@pytest.mark.parametrize("bad", [None, "", "x", 1.5, True])
def test_require_base_version_rejects_non_integers(bad) -> None:
    sketch = new_sketch("base", "Base", "flowchart")
    with pytest.raises(ValueError):
        require_base_version(sketch, bad)

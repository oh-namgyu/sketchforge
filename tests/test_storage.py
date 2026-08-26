"""Storage contract, ported from the loreforge/janusline suite."""

import json
import threading
import time
from pathlib import Path

import pytest

from core.schema import SketchNotFound, slugify
from core.storage import Storage

FLOW = "flowchart TD\n  A[Start] --> B[End]"


@pytest.fixture()
def store(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "data")


def test_roundtrip_blank_start(store: Storage) -> None:
    sketch = store.create_sketch("Payment Flow")
    assert sketch["slug"] == "payment-flow"
    assert sketch["schema"] == 1 and sketch["status"] == "empty"
    assert sketch["versions"] == [] and sketch["current"] == 0
    assert sketch["pending"] is None and sketch["diagram_type"] == "flowchart"

    loaded = store.load_sketch(sketch["slug"])
    assert loaded["title"] == "Payment Flow"
    summaries = store.list_sketches()
    assert [s["slug"] for s in summaries] == [sketch["slug"]]
    assert summaries[0]["version_count"] == 0 and summaries[0]["has_pending"] is False
    assert "versions" not in summaries[0]


def test_roundtrip_with_source(store: Storage) -> None:
    sketch = store.create_sketch("Seeded", diagram_type="sequence", source=FLOW)
    assert sketch["status"] == "drafted" and sketch["current"] == 1
    assert sketch["versions"][0]["source"] == FLOW
    assert sketch["versions"][0]["instruction"] == "manual edit"
    assert store.list_sketches()[0]["version_count"] == 1


def test_defaults_and_slug_dedupe(store: Storage) -> None:
    first = store.create_sketch("Same Title")
    second = store.create_sketch("Same Title")
    third = store.create_sketch("Same Title")
    assert [first["slug"], second["slug"], third["slug"]] == [
        "same-title",
        "same-title-2",
        "same-title-3",
    ]
    assert slugify("....") == "sketch"
    assert store.create_sketch("한국어")["slug"] == "sketch"  # non-ascii title
    assert store.create_sketch(None)["title"] == "Untitled sketch"


@pytest.mark.parametrize("bad", ["../x", "a/b", "Uppercase", "x" * 65, "", "a b", ".."])
def test_slug_traversal_rejected(store: Storage, bad: str) -> None:
    with pytest.raises(ValueError):
        store.sketch_dir(bad)
    with pytest.raises(ValueError):
        store.load_sketch(bad)
    with pytest.raises(ValueError):
        store.delete_sketch(bad)


def test_create_validation(store: Storage) -> None:
    for kwargs in (
        {"title": "x" * 201},
        {"title": 5},
        {"title": "ok", "diagram_type": "uml"},
        {"title": "ok", "diagram_type": 3},
        {"title": "ok", "source": 7},
        {"title": "ok", "source": "x" * 200_001},
    ):
        with pytest.raises(ValueError):
            store.create_sketch(**kwargs)
    assert store.create_sketch("x" * 200)["title"] == "x" * 200


def test_atomic_write_leaves_no_tmp_and_rotates_bak(store: Storage) -> None:
    slug = store.create_sketch("Rotate Me")["slug"]
    store.commit_version(slug, "flowchart TD\n  A --> B")
    store.commit_version(slug, "flowchart TD\n  A --> C")

    folder = store.sketch_dir(slug)
    assert not list(folder.glob("*.tmp"))
    assert json.loads((folder / "sketch.json").read_text())["current"] == 2
    assert json.loads((folder / "sketch.json.bak").read_text())["current"] == 1


def test_corrupt_recovers_from_bak(store: Storage) -> None:
    slug = store.create_sketch("Corrupt Me")["slug"]
    store.commit_version(slug, FLOW)
    store.commit_version(slug, FLOW)  # ensure a .bak exists

    (store.sketch_dir(slug) / "sketch.json").write_text("{not json", encoding="utf-8")
    recovered = store.load_sketch(slug)
    assert recovered["recovered"] is True
    assert recovered["versions"][0]["source"] == FLOW
    assert store.list_sketches()[0]["recovered"] is True

    # a rewrite drops the transient flag from disk
    store.save_sketch(slug, recovered)
    on_disk = json.loads((store.sketch_dir(slug) / "sketch.json").read_text())
    assert "recovered" not in on_disk


def test_corrupt_both_copies_preserves_file_and_restarts_empty(store: Storage) -> None:
    slug = store.create_sketch("Total Loss")["slug"]
    store.commit_version(slug, FLOW)
    store.commit_version(slug, FLOW)

    folder = store.sketch_dir(slug)
    (folder / "sketch.json").write_text("]]] broken", encoding="utf-8")
    (folder / "sketch.json.bak").write_text("also broken {", encoding="utf-8")

    restarted = store.load_sketch(slug)
    assert restarted["data_loss"] is True
    assert restarted["status"] == "empty" and restarted["versions"] == []
    assert restarted["slug"] == slug and restarted["current"] == 0

    preserved = list(folder.glob("sketch.json.corrupt-*"))
    assert len(preserved) == 1
    assert preserved[0].read_text() == "]]] broken"

    on_disk = json.loads((folder / "sketch.json").read_text())
    assert on_disk["status"] == "empty" and "data_loss" not in on_disk
    assert store.list_sketches()[0]["status"] == "empty"


def test_unknown_schema_version_is_read_only(store: Storage) -> None:
    slug = store.create_sketch("From The Future")["slug"]
    path = store.sketch_dir(slug) / "sketch.json"
    data = json.loads(path.read_text())
    data["schema"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")

    assert store.load_sketch(slug)["read_only"] is True
    with pytest.raises(Exception):  # ReadOnlySketch — no writes on a future doc
        store.commit_version(slug, FLOW)


def test_missing_sketch(store: Storage) -> None:
    with pytest.raises(SketchNotFound):
        store.load_sketch("ghost")
    with pytest.raises(SketchNotFound):
        store.delete_sketch("ghost")


def test_concurrent_writes_serialize(store: Storage) -> None:
    slug = store.create_sketch("Race")["slug"]
    errors: list[Exception] = []

    def bump(field: str, times: int) -> None:
        try:
            for i in range(times):
                store.mutate_sketch(slug, lambda s, f=field, v=i: s.update({f: v}))
        except Exception as exc:  # pragma: no cover - surfaced via assert
            errors.append(exc)

    threads = [
        threading.Thread(target=bump, args=("alpha", 40)),
        threading.Thread(target=bump, args=("beta", 40)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    final = store.load_sketch(slug)
    assert "recovered" not in final and "data_loss" not in final
    assert final["alpha"] == 39 and final["beta"] == 39
    assert final["title"] == "Race"


def test_concurrent_commits_produce_contiguous_versions(store: Storage) -> None:
    slug = store.create_sketch("Version Race")["slug"]

    def commit(count: int) -> None:
        for i in range(count):
            store.commit_version(slug, f"flowchart TD\n  A --> N{i}")

    threads = [threading.Thread(target=commit, args=(15,)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final = store.load_sketch(slug)
    assert [v["n"] for v in final["versions"]] == list(range(1, 46))
    assert final["current"] == 45


def test_duplicate_copies_current_source_only(store: Storage) -> None:
    slug = store.create_sketch("Original", diagram_type="er")["slug"]
    store.commit_version(slug, "flowchart TD\n  A --> B")
    store.commit_version(slug, "flowchart TD\n  A --> C")

    copy = store.duplicate_sketch(slug)
    assert copy["slug"] == "original-copy"
    assert copy["title"] == "Original copy" and copy["diagram_type"] == "er"
    assert copy["current"] == 1 and len(copy["versions"]) == 1
    assert copy["versions"][0]["source"] == "flowchart TD\n  A --> C"
    assert copy["versions"][0]["instruction"] == f"duplicated from {slug}"


def test_duplicate_of_blank_stays_blank(store: Storage) -> None:
    slug = store.create_sketch("Blank")["slug"]
    copy = store.duplicate_sketch(slug)
    assert copy["status"] == "empty" and copy["versions"] == []


def test_delete_moves_to_trash_and_purge_expires(store: Storage) -> None:
    slug = store.create_sketch("Trash Me")["slug"]
    name = store.delete_sketch(slug)
    assert not store.sketch_dir(slug).exists()
    assert (store.trash_dir / name).is_dir()
    with pytest.raises(SketchNotFound):
        store.delete_sketch(slug)

    old = store.trash_dir / f"stale-{int(time.time()) - 8 * 86400}"
    old.mkdir()
    (old / "sketch.json").write_text("{}", encoding="utf-8")

    assert store.purge_trash(days=7) == 1
    assert not old.exists()
    assert (store.trash_dir / name).is_dir()

    assert store.purge_trash(days=0) == 1
    assert not (store.trash_dir / name).exists()

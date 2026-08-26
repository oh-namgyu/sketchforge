"""REST surface: envelope, status codes, optimistic concurrency."""

import json
from pathlib import Path

import pytest

from app import create_app

FLOW = "flowchart TD\n  A[Start] --> B[End]"
FLOW2 = "flowchart TD\n  A[Start] --> C[Other]"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    application = create_app(data_dir=tmp_path / "data")
    application.config.update(TESTING=True)
    return application.test_client()


def body(res) -> dict:
    return json.loads(res.data)


def create(client, **payload) -> str:
    res = client.post("/api/sketches", json=payload)
    assert res.status_code == 201, res.data
    return body(res)["data"]["slug"]


# --- envelope --------------------------------------------------------------


def test_list_is_empty_envelope(client) -> None:
    res = client.get("/api/sketches")
    assert res.status_code == 200
    assert body(res) == {"ok": True, "data": []}


def test_security_headers_present(client) -> None:
    res = client.get("/api/sketches")
    assert "script-src 'self'" in res.headers["Content-Security-Policy"]
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["Referrer-Policy"] == "same-origin"


def test_unknown_api_path_is_json_404(client) -> None:
    res = client.get("/api/nope")
    assert res.status_code == 404 and body(res)["ok"] is False


def test_wrong_method_is_json_405(client) -> None:
    res = client.put("/api/sketches")
    assert res.status_code == 405 and body(res)["error"] == "method not allowed"


def test_non_object_body_is_400(client) -> None:
    res = client.post("/api/sketches", json=["nope"])
    assert res.status_code == 400 and body(res)["ok"] is False


# --- create ----------------------------------------------------------------


def test_create_blank(client) -> None:
    res = client.post("/api/sketches", json={"title": "Blank Start"})
    assert res.status_code == 201
    assert body(res)["data"] == {"slug": "blank-start", "current": 0}

    sketch = body(client.get("/api/sketches/blank-start"))["data"]
    assert sketch["status"] == "empty" and sketch["versions"] == []


def test_create_with_no_body_at_all(client) -> None:
    res = client.post("/api/sketches")
    assert res.status_code == 201
    assert body(res)["data"]["slug"] == "untitled-sketch"


def test_create_with_source_starts_at_v1(client) -> None:
    slug = create(client, title="Seeded", diagram_type="sequence", source=FLOW)
    sketch = body(client.get(f"/api/sketches/{slug}"))["data"]
    assert sketch["current"] == 1 and sketch["status"] == "drafted"
    assert sketch["diagram_type"] == "sequence"


def test_create_with_bad_source_is_400(client) -> None:
    res = client.post("/api/sketches", json={"title": "Bad", "source": "uml X"})
    assert res.status_code == 400
    assert "unknown diagram header" in body(res)["error"]
    assert body(client.get("/api/sketches"))["data"] == []


def test_create_with_bad_type_is_400(client) -> None:
    res = client.post("/api/sketches", json={"diagram_type": "uml"})
    assert res.status_code == 400 and "diagram_type" in body(res)["error"]


# --- read / delete / duplicate --------------------------------------------


def test_get_missing_is_404(client) -> None:
    res = client.get("/api/sketches/ghost")
    assert res.status_code == 404 and body(res)["error"] == "sketch not found"


@pytest.mark.parametrize("bad", ["Upper", "with_underscore", "x" * 65])
def test_bad_slug_is_400(client, bad: str) -> None:
    res = client.get(f"/api/sketches/{bad}")
    assert res.status_code == 400 and body(res)["error"] == "invalid slug"


def test_traversal_slug_never_reaches_the_handler(client) -> None:
    assert client.get("/api/sketches/../../etc/passwd").status_code == 404


def test_delete_moves_to_trash(client) -> None:
    slug = create(client, title="Trash Me")
    res = client.delete(f"/api/sketches/{slug}")
    assert res.status_code == 200 and body(res)["data"]["slug"] == slug
    assert client.get(f"/api/sketches/{slug}").status_code == 404
    assert client.delete(f"/api/sketches/{slug}").status_code == 404


def test_duplicate_returns_a_new_slug(client) -> None:
    slug = create(client, title="Original", source=FLOW)
    res = client.post(f"/api/sketches/{slug}/duplicate")
    assert res.status_code == 201
    copy = body(res)["data"]["slug"]
    assert copy != slug
    assert body(client.get(f"/api/sketches/{copy}"))["data"]["versions"][0]["source"] == FLOW


# --- manual save -----------------------------------------------------------


def test_save_version_appends(client) -> None:
    slug = create(client, title="Manual")
    res = client.post(
        f"/api/sketches/{slug}/versions", json={"source": FLOW, "base_version": 0}
    )
    assert res.status_code == 200
    data = body(res)["data"]
    assert data["current"] == 1 and data["dropped"] == 0
    assert data["versions"][0]["instruction"] == "manual edit"

    res = client.post(
        f"/api/sketches/{slug}/versions", json={"source": FLOW2, "base_version": 1}
    )
    assert body(res)["data"]["current"] == 2


def test_save_version_stale_base_is_409(client) -> None:
    slug = create(client, title="Conflict", source=FLOW)
    res = client.post(
        f"/api/sketches/{slug}/versions", json={"source": FLOW2, "base_version": 0}
    )
    assert res.status_code == 409
    assert "current 1" in body(res)["error"]
    # the losing save changed nothing
    assert body(client.get(f"/api/sketches/{slug}"))["data"]["current"] == 1


def test_save_version_missing_base_is_400(client) -> None:
    slug = create(client, title="No Base")
    res = client.post(f"/api/sketches/{slug}/versions", json={"source": FLOW})
    assert res.status_code == 400 and "base_version" in body(res)["error"]


def test_save_version_rejects_bad_source_before_touching_disk(client) -> None:
    slug = create(client, title="Guarded", source=FLOW)
    before = client.get(f"/api/sketches/{slug}").data
    res = client.post(
        f"/api/sketches/{slug}/versions",
        json={"source": "flowchart TD\n A[oops --> B", "base_version": 1},
    )
    assert res.status_code == 400 and "unclosed '['" in body(res)["error"]
    assert client.get(f"/api/sketches/{slug}").data == before


def test_save_version_rejects_hostile_source(client) -> None:
    slug = create(client, title="Hostile")
    res = client.post(
        f"/api/sketches/{slug}/versions",
        json={"source": 'flowchart TD\n A["<script>x</script>"]', "base_version": 0},
    )
    assert res.status_code == 400 and "script tag" in body(res)["error"]


def test_save_version_size_cap(client) -> None:
    slug = create(client, title="Huge")
    payload = "flowchart TD\n" + ("  A --> B\n" * 30_000)
    assert len(payload) > 200_000
    res = client.post(
        f"/api/sketches/{slug}/versions", json={"source": payload, "base_version": 0}
    )
    assert res.status_code == 400 and "too long" in body(res)["error"]


def test_save_version_on_missing_sketch_is_404(client) -> None:
    res = client.post(
        "/api/sketches/ghost/versions", json={"source": FLOW, "base_version": 0}
    )
    assert res.status_code == 404


# --- revert ----------------------------------------------------------------


def test_revert_appends(client) -> None:
    slug = create(client, title="Revert", source=FLOW)
    client.post(f"/api/sketches/{slug}/versions", json={"source": FLOW2, "base_version": 1})

    res = client.post(f"/api/sketches/{slug}/revert", json={"n": 1})
    assert res.status_code == 200
    data = body(res)["data"]
    assert data["current"] == 3 and len(data["versions"]) == 3
    assert data["versions"][2]["source"] == FLOW
    assert data["versions"][2]["instruction"] == "revert to v1"


def test_revert_to_unknown_version_is_404(client) -> None:
    slug = create(client, title="Revert 404", source=FLOW)
    res = client.post(f"/api/sketches/{slug}/revert", json={"n": 7})
    assert res.status_code == 404 and "no version 7" in body(res)["error"]


def test_revert_without_n_is_400(client) -> None:
    slug = create(client, title="Revert 400", source=FLOW)
    res = client.post(f"/api/sketches/{slug}/revert", json={})
    assert res.status_code == 400


# --- listing ---------------------------------------------------------------


def test_list_summaries_carry_counts_and_hide_sources(client) -> None:
    create(client, title="One", source=FLOW)
    create(client, title="Two")
    items = body(client.get("/api/sketches"))["data"]
    assert {item["slug"] for item in items} == {"one", "two"}
    assert all("versions" not in item for item in items)
    by_slug = {item["slug"]: item for item in items}
    assert by_slug["one"]["version_count"] == 1 and by_slug["one"]["status"] == "drafted"
    assert by_slug["two"]["version_count"] == 0 and by_slug["two"]["status"] == "empty"

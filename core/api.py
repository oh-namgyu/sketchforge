"""REST API blueprint. Every response uses the {ok, data|error} envelope."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import Blueprint, Response, current_app, jsonify, request

from .mermaid_check import MermaidSyntaxError, check_source
from .schema import (
    ReadOnlySketch,
    SketchNotFound,
    StorageError,
    VersionConflict,
    VersionNotFound,
    require_base_version,
)
from .storage import Storage

api_bp = Blueprint("api", __name__, url_prefix="/api")


def ok(data: Any, status: int = 200) -> Tuple[Response, int]:
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int, **extra: Any) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def store() -> Storage:
    return current_app.config["STORAGE"]


def _payload() -> Dict[str, Any]:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    return body


@api_bp.get("/sketches")
def list_sketches() -> Tuple[Response, int]:
    return ok(store().list_sketches())


@api_bp.post("/sketches")
def create_sketch() -> Tuple[Response, int]:
    """A blank start is the normal path: title and type are optional hints."""
    body = _payload()
    source = body.get("source")
    if source not in (None, ""):
        check_source(source)
    sketch = store().create_sketch(
        title=body.get("title"),
        diagram_type=body.get("diagram_type"),
        source=source,
    )
    return ok({"slug": sketch["slug"], "current": sketch["current"]}, 201)


@api_bp.get("/sketches/<slug>")
def get_sketch(slug: str) -> Tuple[Response, int]:
    return ok(store().load_sketch(slug))


@api_bp.delete("/sketches/<slug>")
def delete_sketch(slug: str) -> Tuple[Response, int]:
    return ok({"slug": slug, "trashed": store().delete_sketch(slug)})


@api_bp.post("/sketches/<slug>/duplicate")
def duplicate_sketch(slug: str) -> Tuple[Response, int]:
    copy = store().duplicate_sketch(slug)
    return ok({"slug": copy["slug"], "current": copy["current"]}, 201)


@api_bp.post("/sketches/<slug>/versions")
def save_version(slug: str) -> Tuple[Response, int]:
    """Manual save. The client sends the source it edited plus the version it
    started from; a mismatch means another save landed first (409)."""
    body = _payload()
    source = check_source(body.get("source"))
    with store().lock(slug):
        require_base_version(store().load_sketch(slug), body.get("base_version"))
        return ok(store().commit_version(slug, source, "manual edit"))


@api_bp.post("/sketches/<slug>/revert")
def revert(slug: str) -> Tuple[Response, int]:
    """Revert is an append: vN's source comes back as a brand new version."""
    return ok(store().revert_version(slug, _payload().get("n")))


def register_errors(app) -> None:
    """JSON envelope for API errors, including framework-raised ones."""

    @app.errorhandler(MermaidSyntaxError)
    def _bad_source(err: MermaidSyntaxError):
        return fail(str(err) or "invalid mermaid source", 400)

    @app.errorhandler(ValueError)
    def _bad_request(err: ValueError):
        return fail(str(err) or "bad request", 400)

    @app.errorhandler(SketchNotFound)
    def _not_found(err: SketchNotFound):
        return fail("sketch not found", 404)

    @app.errorhandler(VersionNotFound)
    def _no_version(err: VersionNotFound):
        return fail(str(err) or "version not found", 404)

    @app.errorhandler(VersionConflict)
    def _conflict(err: VersionConflict):
        return fail(str(err) or "version conflict", 409)

    @app.errorhandler(ReadOnlySketch)
    def _read_only(err: ReadOnlySketch):
        return fail("sketch was written by a newer version — read only", 409)

    @app.errorhandler(StorageError)
    def _storage(err: StorageError):
        return fail(str(err) or "storage error", 500)

    @app.errorhandler(404)
    def _http_404(err):
        if request.path.startswith("/api/"):
            return fail("not found", 404)
        return err

    @app.errorhandler(405)
    def _http_405(err):
        if request.path.startswith("/api/"):
            return fail("method not allowed", 405)
        return err

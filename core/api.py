"""REST API blueprint. Every response uses the {ok, data|error} envelope."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import Blueprint, Response, current_app, jsonify, request

from .generate import (
    RAW_PREVIEW,
    GenerationError,
    generate_source,
    revise_source,
)
from .llm import LLMError, LLMNotConfigured
from .mermaid_check import MermaidSyntaxError, check_source
from .schema import (
    MAX_INSTRUCTION,
    ReadOnlySketch,
    SketchNotFound,
    StorageError,
    VersionConflict,
    VersionNotFound,
    current_source,
    normalise_pending,
    require_base_version,
    require_text,
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


def llm() -> Any:
    return current_app.config["LLM"]


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


# -- LLM paths --------------------------------------------------------------
#
# Every one of these calls the model *before* the store is touched, and folds
# the result in with a single atomic write. A failure at any stage — no key, a
# provider error, an answer that is not mermaid — therefore leaves sketch.json
# byte for byte as it was. The lock is held across the call so a second request
# on the same sketch queues instead of racing.


def _llm_failure(err: Exception) -> Tuple[Response, int]:
    """One place decides what each provider-side failure looks like on the wire."""
    if isinstance(err, LLMNotConfigured):
        return fail("llm-not-configured", 503)
    if isinstance(err, GenerationError):
        return fail("invalid-llm-output", 502, raw_preview=err.raw[:RAW_PREVIEW])
    return fail(str(err) or "llm-error", 502, retryable=getattr(err, "retryable", False))


@api_bp.post("/sketches/<slug>/generate")
def generate(slug: str) -> Tuple[Response, int]:
    """Intent -> the first version. Only for a sketch that has none yet."""
    intent = require_text(_payload().get("intent"), "intent", MAX_INSTRUCTION)
    with store().lock(slug):
        sketch = store().load_sketch(slug)
        if sketch.get("versions"):
            return fail("sketch already has a diagram — use revise", 409)
        try:
            source = generate_source(llm(), intent, sketch.get("diagram_type"))
        except (LLMNotConfigured, LLMError, GenerationError) as err:
            return _llm_failure(err)
        return ok(store().commit_version(slug, source, intent))


@api_bp.post("/sketches/<slug>/revise")
def revise(slug: str) -> Tuple[Response, int]:
    """Instruction + current source -> a proposal in the single pending slot.

    A new proposal replaces the previous one deliberately: pending is "the last
    thing the model offered", not a queue. It records the version it was built
    from so accept can tell whether the ground moved underneath it.
    """
    instruction = require_text(_payload().get("instruction"), "instruction", MAX_INSTRUCTION)
    with store().lock(slug):
        sketch = store().load_sketch(slug)
        source = current_source(sketch)
        if not source:
            return fail("sketch has no diagram yet — use generate", 409)
        try:
            revised = revise_source(llm(), source, instruction)
        except (LLMNotConfigured, LLMError, GenerationError) as err:
            return _llm_failure(err)
        proposal = normalise_pending(revised, instruction, sketch.get("current") or 0)
        return ok(store().mutate_sketch(slug, lambda doc: doc.update(pending=proposal)))


@api_bp.post("/sketches/<slug>/accept")
def accept(slug: str) -> Tuple[Response, int]:
    """Confirm the pending proposal. Deliberately takes no body.

    The client never sends the source back: what gets committed is what the
    server stored, so nothing a browser holds can be swapped in on the way. A
    version confirmed since the proposal was made makes it stale — 409, and the
    proposal stays put for the client to look at or reject.
    """
    with store().lock(slug):
        sketch = store().load_sketch(slug)
        proposal = sketch.get("pending")
        if not proposal:
            return fail("no pending revision", 409)
        require_base_version(sketch, proposal.get("base_version"))
        instruction = proposal.get("instruction") or "revision"
        source = proposal.get("source") or ""
        return ok(store().commit_version(slug, source, instruction, drop_pending=True))


@api_bp.post("/sketches/<slug>/reject")
def reject(slug: str) -> Tuple[Response, int]:
    """Discard the pending proposal. Versions are untouched — reject only clears."""
    return ok(store().mutate_sketch(slug, lambda doc: doc.update(pending=None)))


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

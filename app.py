"""sketchforge — self-hosted mermaid diagram studio. Factory and entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from flask import Flask, Response, send_from_directory

from core import auth
from core.api import api_bp, register_errors
from core.storage import Storage

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 6183

# script-src 'self' is the last line of defence behind the SVG sanitiser: even
# if markup slipped into the render container, an inline script cannot run.
#
# style-src is the one relaxation. A mermaid diagram carries its theme as a
# <style> block plus style attributes inside the SVG, and under a bare
# default-src 'self' the browser drops both — the diagram renders as unstyled
# black shapes. Inline CSS cannot execute script while script-src stays 'self',
# and the sanitiser has already stripped external url() references out of every
# style it lets through, so the exception is narrow and does not touch the
# property that matters.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"
)


def resolve_data_dir(data_dir: Optional[str | os.PathLike[str]] = None) -> Path:
    if data_dir:
        return Path(data_dir)
    env_dir = os.environ.get("SKETCHFORGE_DATA")
    if env_dir:
        return Path(env_dir)
    return BASE_DIR / "data"


def create_app(
    data_dir: Optional[str | os.PathLike[str]] = None,
    token: Optional[str] = None,
) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
    storage = Storage(resolve_data_dir(data_dir))
    storage.purge_trash(days=int(os.environ.get("SKETCHFORGE_TRASH_DAYS", "7")))
    app.config["STORAGE"] = storage
    app.register_blueprint(api_bp)
    register_errors(app)
    auth.install(app, token if token is not None else os.environ.get("AUTH_TOKEN"))

    @app.get("/")
    def index() -> Response:
        return send_from_directory(STATIC_DIR, "index.html")

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    return app


def main() -> None:
    host = os.environ.get("HOST", DEFAULT_HOST)
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    auth.check_bind(host, os.environ.get("AUTH_TOKEN"))
    create_app().run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()

"""End-to-end fixtures: a real server process driven by a real browser.

The app is started exactly as a user would start it, with two differences that
keep the run hermetic: a temporary data directory and no AUTH_TOKEN. Nothing
else is stubbed — the vendored mermaid bundle and the real CSP are what the
browser sees.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOT_TIMEOUT = 20.0
DROP_ENV = ("AUTH_TOKEN", "ANTHROPIC_API_KEY")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def chromium_ready() -> bool:
    """False when playwright or its chromium build is missing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


def wait_for(url: str, process: subprocess.Popen) -> None:
    deadline = time.time() + BOOT_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(url + "/api/sketches", timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError("server did not come up in time")


def run_app(data_dir: Path, **extra_env: str) -> Iterator[str]:
    port = free_port()
    env = dict(os.environ)
    for key in DROP_ENV:
        env.pop(key, None)
    env.update(
        HOST="127.0.0.1",
        PORT=str(port),
        SKETCHFORGE_DATA=str(data_dir),
        PYTHONUNBUFFERED="1",
        **extra_env,
    )
    process = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=str(ROOT), env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(url, process)
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A keyless instance: no AUTH_TOKEN, no API key, no fake — the default."""
    yield from run_app(tmp_path_factory.mktemp("data"))


@pytest.fixture(scope="session")
def keyless_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A second keyless instance, so tests that need an *empty* store (`server`)
    are not disturbed by tests that only need the absence of a model."""
    yield from run_app(tmp_path_factory.mktemp("keyless-data"))


@pytest.fixture(scope="session")
def fake_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """The same app with the offline drafter wired in (SKETCHFORGE_FAKE=1)."""
    yield from run_app(tmp_path_factory.mktemp("fake-data"), SKETCHFORGE_FAKE="1")


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Skip, never fail, when the machine has no chromium build."""
    if chromium_ready():
        return
    skip = pytest.mark.skip(reason="chromium missing — run: playwright install chromium")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)

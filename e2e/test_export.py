"""Downloads: SVG, PNG and the mermaid source.

Every assertion is made against the file that actually reached the disk, not
against what the page claims it produced — an export is only worth anything if
the bytes are there and are what they should be.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Download, Page, expect

pytestmark = pytest.mark.e2e

FLOW = "flowchart TD\n  A[Start] --> B{Choice}\n  B -->|yes| C[Done]\n  B -->|no| A"
# renders fine and asks, in mermaid's own syntax, to be wired to a callback
PROBE = 'flowchart TD\n  A[Start] --> B[End]\n  click A call alert("pwned")'
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
DANGEROUS = ("<script", "foreignobject", "javascript:", "onerror", "onclick", "onload")


def open_studio(page: Page, keyless_server: str, title: str, source: str, query: str = "") -> str:
    page.goto(keyless_server + "/" + query + "#/")
    expect(page.locator("#view-home")).to_be_visible()
    page.fill("#f-title", title)
    page.click("#f-blank")
    expect(page.locator("#view-studio")).to_be_visible()
    page.fill("#source-editor", source)
    expect(page.locator("#render-stage svg")).to_have_count(1, timeout=8000)
    return page.url.rsplit("#/sketch/", 1)[-1]


def grab(page: Page, button: str) -> Download:
    page.click("#export-menu > summary")
    with page.expect_download() as caught:
        page.click(button)
    return caught.value


def saved_bytes(download: Download) -> bytes:
    path = download.path()
    assert path is not None, "the browser did not keep the download"
    return Path(path).read_bytes()


def test_svg_download_is_the_sanitised_diagram(page: Page, keyless_server: str) -> None:
    open_studio(page, keyless_server, "Export svg", FLOW)
    download = grab(page, "#export-svg")
    assert download.suggested_filename == "export-svg.svg"

    text = saved_bytes(download).decode("utf-8")
    assert text.lstrip().startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in text
    assert "width=" in text and "height=" in text, "a standalone file needs a size"
    for label in ("Start", "Done"):
        assert label in text, "the labels travel with the file"
    lowered = text.lower()
    for token in DANGEROUS:
        assert token not in lowered


def test_svg_download_of_a_probe_source_carries_nothing_executable(
    page: Page, keyless_server: str
) -> None:
    open_studio(page, keyless_server, "Export probe", PROBE)
    text = saved_bytes(grab(page, "#export-svg")).decode("utf-8").lower()
    assert text.lstrip().startswith("<svg")
    for token in DANGEROUS:
        assert token not in text
    assert "alert(" not in text and "pwned" not in text


@pytest.mark.parametrize("button,name", [("#export-png", "png"), ("#export-png2", "png2")])
def test_png_download_is_a_real_image(page: Page, keyless_server: str, button: str, name: str) -> None:
    open_studio(page, keyless_server, "Export " + name, FLOW)
    download = grab(page, button)
    assert download.suggested_filename.endswith(".png")
    data = saved_bytes(download)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 1000, "a real diagram, not an empty canvas"


def test_png_2x_is_larger_than_1x(page: Page, keyless_server: str) -> None:
    open_studio(page, keyless_server, "Export scale", FLOW)
    one = saved_bytes(grab(page, "#export-png"))
    two = saved_bytes(grab(page, "#export-png2"))
    assert len(two) > len(one)


def test_mmd_download_is_the_source_verbatim(page: Page, keyless_server: str) -> None:
    open_studio(page, keyless_server, "Export mmd", FLOW)
    download = grab(page, "#export-mmd")
    assert download.suggested_filename == "export-mmd.mmd"
    assert saved_bytes(download).decode("utf-8") == FLOW


def test_png_failure_says_so_and_offers_the_svg(page: Page, keyless_server: str) -> None:
    """?pngfail=1 forces the rasteriser to fail: a message, never a stub file."""
    open_studio(page, keyless_server, "Export failure", FLOW, query="?pngfail=1")
    downloads: list[Download] = []
    page.on("download", lambda item: downloads.append(item))

    page.click("#export-menu > summary")
    page.click("#export-png")
    expect(page.locator("#notice")).to_contain_text("PNG export failed", timeout=8000)
    expect(page.locator("#notice")).to_contain_text("SVG")
    assert downloads == [], "a failed PNG export must not write a file"

    # the offered fallback works from the same notice
    with page.expect_download() as caught:
        page.locator("#notice button").first.click()
    assert saved_bytes(caught.value).decode("utf-8").lstrip().startswith("<svg")


def test_export_of_an_empty_canvas_explains_itself(page: Page, keyless_server: str) -> None:
    page.goto(keyless_server + "/#/")
    page.fill("#f-title", "Export empty")
    page.click("#f-blank")
    expect(page.locator("#view-studio")).to_be_visible()
    downloads: list[Download] = []
    page.on("download", lambda item: downloads.append(item))

    page.click("#export-menu > summary")
    page.click("#export-svg")
    expect(page.locator("#notice")).to_contain_text("Nothing to export", timeout=8000)
    assert downloads == []

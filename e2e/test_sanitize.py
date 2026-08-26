"""Direct coverage of sanitizeSvg — the allowlist, exercised in a real browser.

The studio probes prove the render path is safe end to end; these prove the
function itself behaves on inputs mermaid would never produce but an attacker
might, so a future refactor of the allowlist fails here first.

page.evaluate runs in an isolated world, which the page CSP does not restrict,
so it can call window.SFSanitize directly.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg">'


@pytest.fixture()
def sanitize(page: Page, server: str):
    page.goto(server + "/#/")
    page.wait_for_function("() => Boolean(window.SFSanitize)")

    def run(markup: str) -> str:
        return page.evaluate(
            "markup => { const n = window.SFSanitize.sanitizeSvg(markup);"
            " return n ? window.SFSanitize.serializeSvg(n) : ''; }",
            markup,
        )

    return run


def wrap(inner: str) -> str:
    return SVG_OPEN + inner + "</svg>"


# --- what survives ---------------------------------------------------------


def test_presentation_elements_survive(sanitize) -> None:
    out = sanitize(
        wrap(
            '<g class="node"><rect x="1" y="2" width="10" height="4" fill="#eee" '
            'stroke="#333" stroke-width="2"/><text x="3" y="4" text-anchor="middle">'
            "<tspan>hello</tspan></text><path d=\"M0 0 L5 5\"/></g>"
        )
    )
    for fragment in ("<g", "<rect", "<text", "<tspan", "<path", "hello", 'fill="#eee"'):
        assert fragment in out


def test_defs_markers_and_gradients_survive(sanitize) -> None:
    out = sanitize(
        wrap(
            '<defs><marker id="arrow" refX="9" markerWidth="8" orient="auto">'
            '<path d="M0 0 L8 4 L0 8 z"/></marker>'
            '<linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>'
            "</defs><line x1='0' y1='0' x2='9' y2='9' marker-end=\"url(#arrow)\"/>"
        )
    )
    assert "<marker" in out and "<linearGradient" in out and "<stop" in out
    assert "url(#arrow)" in out


def test_local_url_reference_in_style_survives(sanitize) -> None:
    out = sanitize(wrap('<rect style="fill:url(#g);stroke:#111" width="4" height="4"/>'))
    assert "url(#g)" in out and "stroke:#111" in out


def test_aria_and_data_attributes_survive(sanitize) -> None:
    out = sanitize(wrap('<g role="img" aria-label="graph" data-id="n1"><rect/></g>'))
    assert 'aria-label="graph"' in out and 'data-id="n1"' in out and 'role="img"' in out


# --- what does not ---------------------------------------------------------


@pytest.mark.parametrize(
    "inner",
    [
        "<script>alert(1)</script>",
        "<script/>",
        '<foreignObject width="10" height="10"><b>x</b></foreignObject>',
        '<image href="http://example.test/x.png"/>',
        "<animate attributeName='x' to='9'/>",
        "<set attributeName='x' to='9'/>",
        "<iframe src='http://example.test'></iframe>",
    ],
)
def test_dangerous_elements_are_dropped(sanitize, inner: str) -> None:
    out = sanitize(wrap(inner + '<rect width="4" height="4"/>'))
    assert "<rect" in out  # the sibling is untouched
    for token in ("script", "foreignObject", "image", "animate", "iframe", "<set"):
        assert token not in out


@pytest.mark.parametrize(
    "attribute",
    [
        'onload="alert(1)"',
        'onclick="alert(1)"',
        'onerror="alert(1)"',
        'ONMOUSEOVER="alert(1)"',
        'onfocus="alert(1)"',
    ],
)
def test_event_handler_attributes_are_dropped(sanitize, attribute: str) -> None:
    out = sanitize(wrap(f'<rect {attribute} width="4" height="4"/>'))
    assert "alert" not in out and "on" not in out.split("<rect")[1].split("/>")[0].lower()


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "blob:http://example.test/x",
        "vbscript:msgbox",
        " javascript:alert(1)",
    ],
)
def test_unsafe_hrefs_are_dropped(sanitize, href: str) -> None:
    out = sanitize(wrap(f'<a href="{href}"><rect width="4" height="4"/></a>'))
    assert "<a" in out and "href" not in out
    assert "javascript" not in out.lower() and "data:" not in out


@pytest.mark.parametrize("href", ["#local", "https://example.test/x", "http://example.test"])
def test_safe_hrefs_survive(sanitize, href: str) -> None:
    out = sanitize(wrap(f'<a href="{href}"><rect width="4" height="4"/></a>'))
    assert href in out


def test_external_url_in_style_attribute_is_neutralised(sanitize) -> None:
    out = sanitize(
        wrap('<rect style="fill:url(http://example.test/t.png)" width="4" height="4"/>')
    )
    assert "example.test" not in out and "fill:none" in out


def test_style_element_is_scrubbed_not_trusted(sanitize) -> None:
    out = sanitize(
        wrap(
            "<style>@import url('http://example.test/x.css');"
            ".n{fill:url(http://example.test/y.svg);background:url(#ok)}</style>"
            '<rect width="4" height="4"/>'
        )
    )
    assert "<style" in out  # the theme block itself is allowed through
    assert "@import" not in out and "example.test" not in out
    assert "url(#ok)" in out


def test_unknown_attributes_are_dropped(sanitize) -> None:
    out = sanitize(wrap('<rect ping="http://example.test" formaction="/x" width="4"/>'))
    assert "ping" not in out and "formaction" not in out and 'width="4"' in out


def test_html_root_is_refused_outright(sanitize) -> None:
    assert sanitize("<html><body><script>alert(1)</script></body></html>") == ""
    assert sanitize("not markup at all") == ""
    assert sanitize("") == ""


def test_nested_hostile_content_is_reached(sanitize) -> None:
    out = sanitize(
        wrap(
            "<g><g><g><script>alert(1)</script>"
            '<rect onclick="alert(1)" width="4" height="4"/></g></g></g>'
        )
    )
    assert "script" not in out and "onclick" not in out and "<rect" in out


def test_comments_and_processing_instructions_are_removed(sanitize) -> None:
    out = sanitize(wrap("<!-- note --><rect width='4' height='4'/>"))
    assert "note" not in out and "<rect" in out

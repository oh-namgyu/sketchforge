"""Browser round trips for the keyless core: edit, render, save, revert — and
the XSS probes that decide whether the render path is trustworthy.

The app ships CSP `script-src 'self'`, so nothing here injects a page script.
Playwright's own evaluate runs in an isolated world and is unaffected; it is
used only to read layout boxes back off the page.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

FLOW = "flowchart TD\n  A[Start] --> B{Choice}\n  B -->|yes| C[Done]\n  B -->|no| A"
FLOW_EDITED = "flowchart TD\n  A[Start] --> B[Middle]\n  B --> C[End]"
BROKEN = "flowchart TD\n  A[Start --> B[End]"

# Three ways a hostile mermaid source tries to become running code. None may
# survive: securityLevel strict, the allowlist sanitiser, the never-called
# bindFunctions and the CSP each stand between them and the document.
PROBES = {
    "script-tag": 'flowchart TD\n  A["<script>window.__pwned=1;alert(1)</script>"] --> B[ok]',
    "click-callback": 'flowchart TD\n  A[Start] --> B[End]\n  click A call alert("pwned")',
    "foreign-object": (
        'flowchart TD\n'
        '  A["<foreignObject width=\'200\' height=\'50\'>'
        '<img src=x onerror=alert(1)></foreignObject>"] --> B[ok]'
    ),
}


def home(page: Page, server: str) -> None:
    page.goto(server + "/#/")
    expect(page.locator("#view-home")).to_be_visible()


def start_blank(page: Page, server: str, title: str, kind: str = "flowchart") -> str:
    home(page, server)
    page.fill("#f-title", title)
    page.click(f'.chip[data-type="{kind}"]')
    page.click("#f-blank")
    expect(page.locator("#view-studio")).to_be_visible()
    expect(page.locator("#studio-title")).to_have_text(title)
    return page.url.rsplit("#/sketch/", 1)[-1]


def type_source(page: Page, source: str) -> None:
    page.fill("#source-editor", source)


def expect_render(page: Page) -> None:
    expect(page.locator("#render-stage svg")).to_have_count(1, timeout=8000)
    expect(page.locator("#render-error")).to_be_hidden()


def save(page: Page) -> None:
    expect(page.locator("#studio-save")).to_be_enabled()
    page.click("#studio-save")
    expect(page.locator("#studio-status")).to_have_text("saved", timeout=8000)


def version_labels(page: Page) -> list[str]:
    options = page.locator("#version-select option")
    return [options.nth(i).inner_text() for i in range(options.count())]


# --- the keyless round trip -----------------------------------------------


def test_blank_to_saved_diagram_round_trip(page: Page, server: str) -> None:
    home(page, server)
    expect(page.locator("#sketch-empty")).to_be_visible()
    expect(page.locator("#sketch-count")).to_have_text("0")

    slug = start_blank(page, server, "Checkout flow")
    expect(page.locator("#version-select")).to_be_disabled()
    expect(page.locator("#studio-save")).to_be_disabled()

    type_source(page, FLOW)
    expect_render(page)
    # a real graph, not an empty frame
    assert page.locator("#render-stage svg .node").count() >= 3
    assert page.locator("#render-stage svg text").count() > 0
    expect(page.locator("#studio-status")).to_have_text("unsaved")

    save(page)
    assert version_labels(page) == ["v1 · manual edit"]
    expect(page.locator("#studio-revert")).to_be_disabled()

    page.reload()
    expect(page.locator("#source-editor")).to_have_value(FLOW)
    expect_render(page)
    assert version_labels(page) == ["v1 · manual edit"]

    home(page, server)
    expect(page.locator(".card")).to_have_count(1)
    expect(page.locator(".card-title")).to_have_text("Checkout flow")
    expect(page.locator(f'.card[data-slug="{slug}"] .badge-plain')).to_have_text("v1")


def test_versions_accumulate_and_revert_appends(page: Page, server: str) -> None:
    start_blank(page, server, "History")
    type_source(page, FLOW)
    expect_render(page)
    save(page)

    type_source(page, FLOW_EDITED)
    expect_render(page)
    save(page)
    assert version_labels(page) == ["v1 · manual edit", "v2 · manual edit"]

    # revert to v1 -> appended as v3 carrying v1's content
    page.select_option("#version-select", "1")
    expect(page.locator("#source-editor")).to_have_value(FLOW)
    expect(page.locator("#studio-revert")).to_be_enabled()
    page.click("#studio-revert")
    expect(page.locator("#version-select")).to_have_value("3", timeout=8000)
    assert version_labels(page) == [
        "v1 · manual edit",
        "v2 · manual edit",
        "v3 · revert to v1",
    ]
    expect(page.locator("#source-editor")).to_have_value(FLOW)
    expect_render(page)

    # the history is intact: v2 is still readable
    page.select_option("#version-select", "2")
    expect(page.locator("#source-editor")).to_have_value(FLOW_EDITED)

    home(page, server)
    expect(page.locator('.card[data-slug="history"] .badge-plain')).to_have_text("v3")


def test_syntax_error_shows_a_panel_and_keeps_working(page: Page, server: str) -> None:
    start_blank(page, server, "Broken source")
    type_source(page, FLOW)
    expect_render(page)

    type_source(page, BROKEN)
    expect(page.locator("#render-error")).to_be_visible(timeout=8000)
    assert (page.locator("#render-error-text").inner_text() or "").strip() != ""
    expect(page.locator("#studio-title")).to_have_text("Broken source")

    # the studio recovers as soon as the source is valid again
    type_source(page, FLOW_EDITED)
    expect_render(page)
    save(page)
    assert version_labels(page) == ["v1 · manual edit"]


def test_stale_save_is_refused_not_merged(page: Page, server: str) -> None:
    slug = start_blank(page, server, "Conflict")
    type_source(page, FLOW)
    expect_render(page)
    save(page)

    # another client confirms a version while this tab is still editing
    other = page.request.post(
        server + f"/api/sketches/{slug}/versions",
        data={"source": FLOW_EDITED, "base_version": 1},
        headers={"Origin": server},
    )
    assert other.status == 200

    type_source(page, "flowchart TD\n  A[Start] --> Z[Mine]")
    expect_render(page)
    page.click("#studio-save")
    expect(page.locator("#notice")).to_contain_text("moved on", timeout=8000)
    # the text the user typed is still in front of them
    expect(page.locator("#source-editor")).to_have_value(
        "flowchart TD\n  A[Start] --> Z[Mine]"
    )


# --- XSS probes ------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PROBES))
def test_xss_probe_never_executes(page: Page, server: str, name: str) -> None:
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    start_blank(page, server, "Probe " + name)
    type_source(page, PROBES[name])
    # either it renders (defanged) or it fails to parse — never a dialog
    page.wait_for_timeout(2500)

    container = page.locator("#render-canvas")
    assert container.locator("script").count() == 0
    assert container.locator("foreignObject").count() == 0
    assert container.locator("iframe, object, embed").count() == 0

    markup = container.inner_html()
    assert "<script" not in markup.lower()
    assert "foreignobject" not in markup.lower()
    assert "onerror" not in markup.lower()
    assert "javascript:" not in markup.lower()

    assert dialogs == [], f"probe {name} raised a dialog: {dialogs}"
    assert page.evaluate("() => window.__pwned === undefined") is True
    assert errors == [], f"probe {name} broke the page: {errors}"

    # whatever the probe did, the studio is still usable
    type_source(page, FLOW)
    expect_render(page)


def test_probe_source_that_renders_keeps_its_labels_as_text(page: Page, server: str) -> None:
    """A hostile label survives as literal text, not as markup."""
    start_blank(page, server, "Literal label")
    type_source(page, 'flowchart TD\n  A["a < b & c > d"] --> B[ok]')
    expect_render(page)
    text = page.locator("#render-stage svg").text_content() or ""
    assert "a < b & c > d" in text


# --- layout ----------------------------------------------------------------


def test_mobile_viewport_stacks_editor_over_canvas(page: Page, server: str) -> None:
    start_blank(page, server, "Mobile stack")
    type_source(page, FLOW)
    expect_render(page)

    page.set_viewport_size({"width": 420, "height": 900})
    page.wait_for_timeout(300)
    editor = page.locator(".pane-editor").bounding_box()
    canvas = page.locator(".pane-canvas").bounding_box()
    assert editor and canvas
    assert canvas["y"] >= editor["y"] + editor["height"] - 2, "panes should stack"
    assert abs(canvas["x"] - editor["x"]) < 2, "panes should share the left edge"
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), "no horizontal scroll on a phone"

    page.set_viewport_size({"width": 1280, "height": 900})
    page.wait_for_timeout(300)
    editor = page.locator(".pane-editor").bounding_box()
    canvas = page.locator(".pane-canvas").bounding_box()
    assert canvas["x"] > editor["x"], "panes should sit side by side on a desktop"


def test_zoom_controls_move_the_stage(page: Page, server: str) -> None:
    start_blank(page, server, "Zoom")
    type_source(page, FLOW)
    expect_render(page)

    expect(page.locator("#zoom-label")).to_have_text("100%")
    page.click("#zoom-in")
    expect(page.locator("#zoom-label")).to_have_text("120%")
    page.click("#zoom-out")
    page.click("#zoom-out")
    expect(page.locator("#zoom-label")).to_have_text("80%")
    page.click("#zoom-reset")
    expect(page.locator("#zoom-label")).to_have_text("100%")


def test_starter_snippet_matches_the_chosen_type(page: Page, server: str) -> None:
    start_blank(page, server, "Sequence starter", kind="sequence")
    page.click("#studio-starter")
    expect(page.locator("#source-editor")).to_have_value(
        "sequenceDiagram\n  Client->>Server: request\n  Server-->>Client: response"
    )
    expect_render(page)
    save(page)
    home(page, server)
    expect(page.locator('.card[data-slug="sequence-starter"] .badge-sequence')).to_have_text(
        "sequence"
    )

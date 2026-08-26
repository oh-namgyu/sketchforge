"""The smoke check is a UX early-reject, not a security boundary.

These tests pin the messages a user sees, not a safety claim: anything that
slips through is defanged later by the SVG allowlist sanitiser and the CSP.
"""

import pytest

from core.mermaid_check import (
    MermaidSyntaxError,
    check_source,
    header_of,
    hostile_tokens,
    known_header,
    strip_noise,
    unbalanced,
)


@pytest.mark.parametrize(
    "source",
    [
        "flowchart TD\n  A[Start] --> B[End]",
        "graph LR\n  A-->B",
        "sequenceDiagram\n  Alice->>Bob: hi",
        "stateDiagram-v2\n  [*] --> Idle",
        "erDiagram\n  CUSTOMER ||--o{ ORDER : places",
        "classDiagram\n  class Animal",
        "gantt\n  title A",
        "pie\n  title Votes",
        "mindmap\n  root",
        "  \n\nflowchart TD\n  A --> B",
        "---\ntitle: Framed\n---\nflowchart TD\n  A --> B",
        "%%{init: {'theme':'neutral'}}%%\nflowchart TD\n  A --> B",
        "%% a comment\nflowchart TD\n  A --> B",
        'flowchart TD\n  A["a (paren) inside"] --> B',
        'flowchart TD\n  A["say \\"hi\\""] --> B',
    ],
)
def test_valid_sources_pass(source: str) -> None:
    assert check_source(source) == source


@pytest.mark.parametrize(
    "source,fragment",
    [
        ("", "empty"),
        ("   \n  ", "empty"),
        ("%% only a comment", "no diagram content"),
        ("uml TD\n A --> B", "unknown diagram header"),
        ("<div>hello</div>", "unknown diagram header"),
        ("flowchart TD\n  A[Start --> B", "unclosed '['"),
        ("flowchart TD\n  A[Start]] --> B", "unbalanced ']'"),
        ('flowchart TD\n  A["unclosed --> B', "unclosed double quote"),
        ("x" * 200_001, "too long"),
    ],
)
def test_invalid_sources_rejected(source: str, fragment: str) -> None:
    with pytest.raises(MermaidSyntaxError) as err:
        check_source(source)
    assert fragment in str(err.value)


def test_non_string_rejected() -> None:
    with pytest.raises(MermaidSyntaxError):
        check_source(None)


@pytest.mark.parametrize(
    "source,label",
    [
        ('flowchart TD\n  A["<script>alert(1)</script>"] --> B', "script tag"),
        ("flowchart TD\n  A --> B\n  click A \"javascript:alert(1)\"", "javascript: url"),
        ('flowchart TD\n  A["<foreignObject><b>x</b></foreignObject>"] --> B',
         "foreignObject element"),
        ('flowchart TD\n  A["<img onerror=alert(1)>"] --> B',
         "inline event handler attribute"),
    ],
)
def test_hostile_tokens_are_early_rejected(source: str, label: str) -> None:
    assert label in hostile_tokens(source)
    with pytest.raises(MermaidSyntaxError) as err:
        check_source(source)
    assert "rejected" in str(err.value) and label in str(err.value)


def test_hostile_check_is_case_insensitive() -> None:
    assert hostile_tokens('flowchart TD\n  A["<SCRIPT>x</SCRIPT>"]') == ["script tag"]


def test_clean_source_has_no_hostile_tokens() -> None:
    assert hostile_tokens("flowchart TD\n  A[One] --> B[Two]") == []


def test_strip_noise_removes_frontmatter_directives_and_comments() -> None:
    source = (
        "---\ntitle: T\n---\n"
        "%%{init: {'theme':'dark'}}%%\n"
        "%% side note\n"
        "flowchart TD\n  A --> B"
    )
    cleaned = strip_noise(source)
    assert "title: T" not in cleaned and "init" not in cleaned
    assert "side note" not in cleaned
    assert "flowchart TD" in cleaned


def test_header_helpers() -> None:
    assert header_of("---\ntitle: T\n---\nflowchart TD") == "flowchart TD"
    assert header_of("   ") == ""
    assert known_header("flowchart") is True
    assert known_header("flowchartX TD") is False
    assert known_header("graph;A-->B") is True


def test_unbalanced_ignores_brackets_inside_quotes() -> None:
    assert unbalanced('flowchart TD\n  A["]]]"] --> B') == ""
    assert unbalanced("flowchart TD\n  A{Choice} --> B") == ""
    assert unbalanced("flowchart TD\n  A(Round --> B") == "unclosed '('"

"""Lightweight server-side mermaid smoke check.

ROLE — read this before trusting it for anything:

    This is a UX early-reject, NOT a security boundary.

Mermaid's input language is large and evolving; no keyword blacklist can decide
whether a source is safe. The security boundary is the *output* side and lives
in three places outside this file:

    1. mermaid is initialised with securityLevel: 'strict'
    2. every rendered SVG passes an allowlist sanitiser (static/js/sanitize.js)
       before it touches the DOM, and the same function runs before export
    3. the response CSP is "default-src 'self'; script-src 'self'"

What this module does is cheaper and shallower: it catches an obviously broken
or obviously hostile source at save time so the user gets a message instead of
a blank canvas. Full parsing happens in the browser via mermaid.parse(), which
is the authoritative syntax gate.
"""

from __future__ import annotations

import re
from typing import List, Tuple

from .schema import MAX_SOURCE

# Diagram headers mermaid 11 understands. Unknown headers are rejected here but
# a user can always widen this list — being wrong costs a save, not safety.
KNOWN_HEADERS: Tuple[str, ...] = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "classDiagram-v2",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
    "quadrantChart",
    "requirementDiagram",
    "gitGraph",
    "mindmap",
    "timeline",
    "zenuml",
    "sankey-beta",
    "xychart-beta",
    "block-beta",
    "packet-beta",
    "architecture-beta",
    "radar-beta",
    "treemap-beta",
    "kanban",
    "C4Context",
    "C4Container",
    "C4Component",
    "C4Dynamic",
    "C4Deployment",
    "info",
)

# Obvious malice, rejected early so the editor can say why. Anything that slips
# past this is still defanged by the output sanitiser — see the module docstring.
HOSTILE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"<\s*script", "script tag"),
    (r"javascript\s*:", "javascript: url"),
    (r"<\s*foreignObject", "foreignObject element"),
    (r"\bon[a-zA-Z]{2,}\s*=", "inline event handler attribute"),
)

# Headers whose grammar uses brackets asymmetrically, so the balance heuristic
# below would produce false rejects. ER cardinality (`||--o{`, `}o--||`) is the
# clearest case: a lone brace there is correct syntax.
BALANCE_EXEMPT = ("erDiagram",)

PAIRS = {")": "(", "]": "[", "}": "{"}
OPENERS = set(PAIRS.values())
FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
DIRECTIVE_RE = re.compile(r"%%\{.*?\}%%", re.DOTALL)
COMMENT_RE = re.compile(r"^\s*%%(?!\{).*$", re.MULTILINE)


class MermaidSyntaxError(ValueError):
    """The source failed the smoke check. Message is safe to show a user."""


def strip_noise(source: str) -> str:
    """Drop YAML frontmatter, %%{init}%% directives and %% comments."""
    without_front = FRONTMATTER_RE.sub("", source)
    return COMMENT_RE.sub("", DIRECTIVE_RE.sub("", without_front))


def header_of(source: str) -> str:
    """The first meaningful token, or "" when the source has no content."""
    for line in strip_noise(source).splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def known_header(source: str) -> bool:
    head = header_of(source)
    return any(
        head == name or head.startswith(name + " ") or head.startswith(name + "\t")
        or head.startswith(name + ";") or head.startswith(name + ":")
        for name in KNOWN_HEADERS
    )


def hostile_tokens(source: str) -> List[str]:
    """Names of the early-reject patterns present. Empty means nothing obvious."""
    return [
        label
        for pattern, label in HOSTILE_PATTERNS
        if re.search(pattern, source, re.IGNORECASE)
    ]


def unbalanced(source: str) -> str:
    """"" when brackets and double quotes look balanced, else a short reason.

    A heuristic on purpose: quoted spans are skipped so a bracket inside a label
    does not count, and anything subtler is left to mermaid.parse().
    """
    if header_of(source).startswith(BALANCE_EXEMPT):
        return ""
    text = strip_noise(source)
    stack: List[str] = []
    in_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and in_quote:
            index += 2
            continue
        if char == '"':
            in_quote = not in_quote
        elif not in_quote:
            if char in OPENERS:
                stack.append(char)
            elif char in PAIRS:
                if not stack or stack[-1] != PAIRS[char]:
                    return f"unbalanced '{char}'"
                stack.pop()
        index += 1
    if in_quote:
        return "unclosed double quote"
    if stack:
        return f"unclosed '{stack[-1]}'"
    return ""


def check_source(source: str) -> str:
    """Validate and return the source, or raise MermaidSyntaxError."""
    if not isinstance(source, str):
        raise MermaidSyntaxError("source must be a string")
    if len(source) > MAX_SOURCE:
        raise MermaidSyntaxError(f"source is too long (max {MAX_SOURCE} characters)")
    if not source.strip():
        raise MermaidSyntaxError("source is empty")
    found = hostile_tokens(source)
    if found:
        raise MermaidSyntaxError("source rejected: " + ", ".join(found))
    if not header_of(source):
        raise MermaidSyntaxError("source has no diagram content")
    if not known_header(source):
        raise MermaidSyntaxError(
            f"unknown diagram header: {header_of(source)[:60]!r}"
        )
    reason = unbalanced(source)
    if reason:
        raise MermaidSyntaxError(reason)
    return source

"""Deterministic offline drafter for demos and browser tests (SKETCHFORGE_FAKE=1).

No key, no network, same interface as core.llm.AnthropicText. It reads the real
prompts rather than a copy, which is what makes it useful beyond convenience:

* it recovers the diagram from the <current-source> block and the request from the
  INSTRUCTION line, so it only works while those two stay separate — a revise
  prompt that lost its data block would come back as garbage;
* it refuses outright when the system prompt no longer carries the injection
  rule, so the shield cannot be deleted without a test going red;
* the generate answer is fenced on purpose, so every demo run exercises fence
  stripping;
* an instruction containing "break" always answers with something that is not a
  diagram, which drives the retry-then-502 path on demand.
"""

from __future__ import annotations

import re

from .generate import (
    INJECTION_RULE,
    INSTRUCTION_MARK,
    INTENT_MARK,
    SOURCE_CLOSE,
    SOURCE_OPEN,
)

BROKEN_ANSWER = "I am afraid this is prose, not a diagram."
SHIELD_MISSING = "the revise prompt lost its injection shield"
RENAME_RE = re.compile(r"rename\s+(\S+)\s+to\s+(\S+)", re.IGNORECASE)
WORD_RE = re.compile(r"[A-Za-z0-9]+")
COMMENT_SAFE_RE = re.compile(r"[^\w ,.-]+")
MIN_WORD = 2


def _line_after(text: str, mark: str) -> str:
    """The remainder of the first line that starts with `mark`."""
    for line in text.splitlines():
        if line.startswith(mark):
            return line[len(mark) :].strip()
    return ""


def _block(text: str) -> str:
    body = text.partition(SOURCE_OPEN)[2].rpartition(SOURCE_CLOSE)[0]
    return body.strip("\n")


def keyword_of(intent: str) -> str:
    """First word worth naming a node after — deterministic, never empty."""
    for word in WORD_RE.findall(intent):
        if len(word) >= MIN_WORD + 1:
            return word
    return "sketch"


def _target(instruction: str, after: str) -> str:
    tail = instruction.lower().partition(after)[2]
    for word in WORD_RE.findall(tail):
        if len(word) >= MIN_WORD:
            return word
    return "step"


def fake_generate(user: str) -> str:
    """A fixed flowchart carrying one keyword from the intent, inside a fence."""
    keyword = keyword_of(_line_after(user, INTENT_MARK))
    node = keyword.upper()
    return (
        "```mermaid\n"
        "flowchart TD\n"
        "  START[Start] --> " + node + "[" + keyword + "]\n"
        "  " + node + " --> DONE[Done]\n"
        "```"
    )


def _addition(source: str, target: str) -> str:
    """One extra line in the grammar the current header already uses."""
    header = (source.strip().split() or [""])[0]
    node = target.upper()
    if header == "sequenceDiagram":
        return "  Client->>Server: " + target
    if header.startswith("stateDiagram"):
        return "  Idle --> " + node + ": " + target
    if header == "erDiagram":
        return "  ORDER ||--o{ " + node + " : has"
    return "  " + node + "[" + target + "] --> " + node + "_OK[ok]"


def fake_revise(system: str, user: str) -> str:
    """Recognisable transformations, chosen by what the instruction asks for."""
    if INJECTION_RULE not in system:
        return SHIELD_MISSING
    source = _block(user)
    instruction = _line_after(user, INSTRUCTION_MARK)
    lowered = instruction.lower()
    if "break" in lowered:
        return BROKEN_ANSWER
    rename = RENAME_RE.search(instruction)
    if rename:
        return source.replace(rename.group(1), rename.group(2))
    if "add" in lowered:
        return source + "\n" + _addition(source, _target(lowered, "add"))
    return source + "\n  %% revised: " + COMMENT_SAFE_RE.sub(" ", instruction).strip()


class FakeText:
    """Same interface as core.llm.AnthropicText, without the provider."""

    def generate(self, system: str, user: str) -> str:
        if SOURCE_OPEN in user:
            return fake_revise(system, user)
        return fake_generate(user)

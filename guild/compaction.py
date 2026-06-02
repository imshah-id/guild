"""Compaction: shrink agent output before it is fed to the next agent, to save tokens.

Forward-fed context is the main variable cost in the pipeline: a coder's report flowing into
review, review findings flowing into a fix, research flowing into implementation. We compact it
heuristically, with NO extra model calls (which would defeat the point): drop noise, drop review
nit-lines, and truncate on a clean line boundary with a marker. Full outputs are always kept on
disk in result.md; only what travels onward and what is stored in state.json is compacted.
"""
from __future__ import annotations

import re

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_MULTI_BLANK = re.compile(r"\n\s*\n\s*\n+")
# Lines that are pure nits or praise: safe to drop when feeding a fix step.
_DROP_LINE = re.compile(
    r"^\s*[-*#>\s]*\(?(nit|minor|style|optional|lgtm|looks good|nice|great|praise)\b",
    re.IGNORECASE,
)


def strip_noise(text: str) -> str:
    """Remove ANSI escapes, collapse runs of blank lines, trim edges."""
    text = _ANSI.sub("", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


def truncate(text: str, max_chars: int) -> str:
    """Truncate to max_chars on the last clean line boundary, noting how much was dropped."""
    if len(text) <= max_chars:
        return text
    head = text[:max_chars]
    newline = head.rfind("\n")
    if newline > int(max_chars * 0.6):
        head = head[:newline]
    dropped = len(text) - len(head)
    return f"{head}\n[... compacted: {dropped} chars dropped, full output in result.md ...]"


def report(text: str, max_chars: int) -> str:
    """Generic compaction for a coder/scout report or a stored summary."""
    return truncate(strip_noise(text), max_chars)


def review_findings(text: str, max_chars: int) -> str:
    """Compaction for a review fed into a fix: drop nit/praise lines, keep the actionable rest."""
    cleaned = strip_noise(text)
    kept = [line for line in cleaned.splitlines() if not _DROP_LINE.search(line)]
    body = "\n".join(kept).strip() or cleaned
    return truncate(body, max_chars)

"""Project context: the brief every agent loads, from `<project>/.guild/context.md`."""
from __future__ import annotations

from . import config


def load_brief() -> str:
    """The project brief, or empty string if the project has no context.md yet."""
    path = config.CONTEXT_PATH
    if path is None:
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def load_rules() -> str:
    """The project's engineering rule packs from `.guild/rules.md`, or "" if there are none.
    Injected into every agent prompt alongside the brief so the whole team builds to the same
    standard."""
    path = config.RULES_PATH
    if path is None:
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def has_brief() -> bool:
    return bool(load_brief().strip())

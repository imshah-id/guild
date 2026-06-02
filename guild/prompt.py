"""Tiny interactive prompts for the foreground commands (init, roles).

Stdlib `input` only. Every prompt degrades safely: when stdin/stderr is not a TTY (a pipe, CI, a
captured test run) it returns the default without blocking, so the same code path works
interactively and non-interactively. Prompt text goes to stderr to match the rest of the
foreground UI; the typed answer is read from stdin.
"""
from __future__ import annotations

import sys
from typing import Mapping, Sequence

from . import render


def interactive() -> bool:
    """True only when we can actually ask a human (a real terminal on both ends)."""
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (ValueError, OSError):
        return False


def _ask(prompt: str) -> str | None:
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        return input().strip()
    except (EOFError, KeyboardInterrupt):
        return None


def choose(label: str, options: Sequence[str], default: str, *,
           descriptions: Mapping[str, str] | None = None) -> str:
    """Pick one of `options`. Accepts a 1-based number or a (prefix of a) name; empty keeps the
    default. Returns `default` immediately when not interactive."""
    options = list(options)
    if default not in options and options:
        default = options[0]
    if not interactive() or not options:
        return default

    render.say("")
    render.say(render.section(label))
    for index, opt in enumerate(options, start=1):
        mark = f"  {render.GREEN}(default){render.RESET}" if opt == default else ""
        desc = ""
        if descriptions and descriptions.get(opt):
            desc = f"  {render.DIM}{descriptions[opt]}{render.RESET}"
        render.say(f"  {index}. {opt}{mark}{desc}")
    while True:
        answer = _ask(f"  choose [1-{len(options)}] or name, enter={default}: ")
        if answer is None or answer == "":
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        matches = [opt for opt in options if opt == answer or opt.startswith(answer)]
        if len(matches) == 1:
            return matches[0]
        render.say(f"  {render.DIM}pick a number 1-{len(options)} or a name{render.RESET}")


def multi_choose(label: str, options: Sequence[str], defaults: Sequence[str], *,
                 descriptions: Mapping[str, str] | None = None) -> list[str]:
    """Pick any subset of `options` (comma/space-separated numbers or names). Empty keeps the
    defaults; "none" selects nothing. Returns `defaults` (filtered to valid options) when not
    interactive."""
    options = list(options)
    valid_defaults = [opt for opt in defaults if opt in options]
    if not interactive() or not options:
        return valid_defaults

    render.say("")
    render.say(render.section(label))
    for index, opt in enumerate(options, start=1):
        mark = f"  {render.GREEN}(default){render.RESET}" if opt in valid_defaults else ""
        desc = ""
        if descriptions and descriptions.get(opt):
            desc = f"  {render.DIM}{descriptions[opt]}{render.RESET}"
        render.say(f"  {index}. {opt}{mark}{desc}")
    default_label = ", ".join(valid_defaults) if valid_defaults else "none"
    while True:
        answer = _ask(f"  choose any (e.g. 1,3 or names), 'none', enter={default_label}: ")
        if answer is None or answer == "":
            return valid_defaults
        if answer.lower() == "none":
            return []
        tokens = [tok for tok in answer.replace(",", " ").split() if tok]
        picked: list[str] = []
        ok = True
        for token in tokens:
            if token.isdigit() and 1 <= int(token) <= len(options):
                picked.append(options[int(token) - 1])
                continue
            matches = [opt for opt in options if opt == token or opt.startswith(token)]
            if len(matches) == 1:
                picked.append(matches[0])
            else:
                ok = False
                break
        if ok:
            # Preserve option order, drop duplicates.
            return [opt for opt in options if opt in set(picked)]
        render.say(f"  {render.DIM}use numbers 1-{len(options)} or names, separated by spaces/commas{render.RESET}")


def confirm(label: str, *, default: bool = True) -> bool:
    """Yes/no. Returns `default` when not interactive."""
    if not interactive():
        return default
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = _ask(f"  {label} [{suffix}]: ")
        if answer is None or answer == "":
            return default
        low = answer.lower()
        if low in ("y", "yes"):
            return True
        if low in ("n", "no"):
            return False

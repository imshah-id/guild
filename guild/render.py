"""Terminal rendering for the foreground `run`: colors, a spinner, and status lines.

Kept separate from the curses monitor so the interactive run stays simple line output that
interleaves cleanly with approval prompts.
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
import time


def _supports_color() -> bool:
    return (
        sys.stderr.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM", "") not in ("", "dumb")
    )


_ON = _supports_color()


def _code(seq: str) -> str:
    return seq if _ON else ""


RESET = _code("\033[0m")
DIM = _code("\033[2m")
BOLD = _code("\033[1m")
CYAN = _code("\033[36m")
GREEN = _code("\033[32m")
YELLOW = _code("\033[33m")
RED = _code("\033[31m")
BLUE = _code("\033[34m")
MAGENTA = _code("\033[35m")

_STATUS_COLOR = {
    "done": GREEN,
    "running": CYAN,
    "failed": RED,
    "blocked": RED,
    "needs_approval": YELLOW,
    "skipped": DIM,
    "pending": DIM,
}

_STATUS_MARK = {
    "done": "OK",
    "running": ">>",
    "failed": "XX",
    "blocked": "!!",
    "needs_approval": "??",
    "skipped": "--",
    "pending": "..",
}

_PHASE_COLOR = {
    "research": BLUE,
    "implement": CYAN,
    "review": MAGENTA,
    "test": YELLOW,
    "fix": YELLOW,
    "plan": GREEN,
}


def phase_color(phase: str) -> str:
    return _PHASE_COLOR.get(phase, "")


def status_mark(status: str) -> str:
    """Small colored status marker that still reads clearly without ANSI support."""
    color = _STATUS_COLOR.get(status, "")
    mark = _STATUS_MARK.get(status, "  ")
    return f"{color}{mark}{RESET}"


def chip(text: str, *, color: str = "") -> str:
    return f"{color}[{text}]{RESET}"


def phase_chip(phase: str, width: int = 9) -> str:
    label = phase.upper()[:width].ljust(width)
    return chip(label, color=phase_color(phase))


def status_chip(status: str) -> str:
    return chip(status.replace("_", "-"), color=_STATUS_COLOR.get(status, ""))


def progress(done: int, total: int, width: int = 18) -> str:
    if total <= 0:
        return f"[{'-' * width}] 0/0"
    filled = round((done / total) * width)
    filled = max(0, min(width, filled))
    return f"[{'#' * filled}{'-' * (width - filled)}] {done}/{total}"


def section(title: str, detail: str = "") -> str:
    suffix = f" {DIM}{detail}{RESET}" if detail else ""
    return f"{BOLD}{title}{RESET}{suffix}"


def kv(label: str, value: object, width: int = 11) -> str:
    return f"  {DIM}{label:<{width}}{RESET} {value}"


def banner(title: str, *items: tuple[str, object]) -> str:
    meta = "  ".join(f"{DIM}{key}{RESET} {value}" for key, value in items if value not in ("", None))
    return f"{BOLD}{title}{RESET}" + (f"\n{meta}" if meta else "")


def step_row(index: int, phase: str, status: str, title: str, *, agent: str = "",
             elapsed: int = 0, verdict: str = "", extra: str = "") -> str:
    bits = [
        status_mark(status),
        phase_chip(phase),
        title,
    ]
    if index > 0:
        bits.insert(0, f"  {index:>2}")
    else:
        bits.insert(0, "  ")
    meta: list[str] = []
    if agent:
        meta.append(agent)
    if elapsed:
        meta.append(f"{elapsed}s")
    if verdict:
        meta.append(verdict)
    if extra:
        meta.append(extra)
    return " ".join(bits) + (f"  {DIM}{'  '.join(meta)}{RESET}" if meta else "")


def say(msg: str = "") -> None:
    print(msg, file=sys.stderr, flush=True)


def out(msg: str = "") -> None:
    """Print to stdout, for command output that may be piped or captured."""
    print(msg, flush=True)


def rule(width: int = 64) -> str:
    return DIM + ("-" * width) + RESET


class Spinner:
    """Animate a single line on stderr while a blocking call runs."""

    def __init__(self, label: str):
        self.label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start = 0.0

    def __enter__(self) -> "Spinner":
        self._start = time.time()
        if sys.stderr.isatty():
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            say(f"  ... {self.label}")
        return self

    def _spin(self) -> None:
        for ch in itertools.cycle("|/-\\"):
            if self._stop.is_set():
                break
            elapsed = int(time.time() - self._start)
            sys.stderr.write(f"\r  {CYAN}{ch}{RESET} {self.label}  {DIM}{elapsed}s{RESET}\033[K")
            sys.stderr.flush()
            time.sleep(0.1)

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
        if sys.stderr.isatty():
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

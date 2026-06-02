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

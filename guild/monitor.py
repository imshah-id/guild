"""Live, read-only dashboard for a session. Run it in a second pane while `run` works.

It only reads state.json and tails the active step's log, so it can never disturb a run.
"""
from __future__ import annotations

import curses
import json
import sys
import time
from pathlib import Path

from . import render, state

_STATUS_ICON = {
    "done": "ok",
    "running": "..",
    "failed": "XX",
    "pending": "  ",
    "blocked": "!!",
    "needs_approval": "?>",
    "skipped": "--",
}


def _elapsed(step: dict) -> int:
    started = step.get("started", 0.0) or 0.0
    if not started:
        return 0
    ended = step.get("ended", 0.0) or 0.0
    return int((ended if ended else time.time()) - started)


def _active(data: dict) -> dict | None:
    for step in data.get("steps", []):
        if step.get("status") == "running":
            return step
    return None


def _tail(path: Path, lines: int) -> list[str]:
    try:
        content = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def watch(state_path: Path) -> None:
    if not sys.stdout.isatty():
        print("\n".join(snapshot_lines(state.load_dict(state_path))))
        return
    curses.wrapper(_loop, state_path)


def snapshot_lines(data: dict | None) -> list[str]:
    if not data:
        return ["no session data"]
    steps = data.get("steps", [])
    done = sum(1 for step in steps if step.get("status") in ("done", "skipped"))
    lines = [
        f"session {data.get('id')}  [{data.get('status')}]  goal: {data.get('goal')}",
        render.kv("progress", render.progress(done, len(steps))),
    ]
    for index, step in enumerate(steps, start=1):
        lines.append(render.step_row(
            index,
            step.get("phase", ""),
            step.get("status", "pending"),
            step.get("title", ""),
            agent=step.get("agent", ""),
            elapsed=_elapsed(step),
            verdict=step.get("verdict", ""),
        ))
    return lines


def snapshot_json(data: dict | None) -> str:
    return json.dumps(data or {}, indent=2)


def _loop(stdscr: "curses.window", state_path: Path) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(500)
    use_color = curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        curses.init_pair(4, curses.COLOR_CYAN, -1)

    while True:
        data = state.load_dict(state_path)
        if data is not None:
            _draw(stdscr, data, use_color)
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break


def _color_for(status: str) -> int:
    return {
        "done": curses.color_pair(1),
        "running": curses.color_pair(4),
        "failed": curses.color_pair(3),
        "blocked": curses.color_pair(3),
        "needs_approval": curses.color_pair(2),
    }.get(status, 0)


def _draw(stdscr: "curses.window", data: dict, use_color: bool) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    w = max(width - 1, 10)

    status = str(data.get("status", "")).upper()
    stdscr.addnstr(0, 0, f" guild   -   {status}", w, curses.A_BOLD)
    stdscr.addnstr(1, 0, f" session {data.get('id','')}", w, curses.A_DIM)
    stdscr.addnstr(2, 0, f" goal: {data.get('goal','')}", w)

    row = 4
    steps = data.get("steps", [])
    for step in steps:
        if row >= height - 9:
            stdscr.addnstr(row, 0, f"  ... {len(steps) - (row - 4)} more", w, curses.A_DIM)
            break
        st = step.get("status", "pending")
        icon = _STATUS_ICON.get(st, "  ")
        title = step.get("title", "")[: max(w - 44, 8)]
        agent = step.get("agent", "")
        line = f"  [{icon}] {step.get('phase','')[:9]:9} {title}"
        meta = f"{agent:7} {_elapsed(step):>4}s {step.get('verdict','')}"
        attr = _color_for(st) if use_color else 0
        stdscr.addnstr(row, 0, line, w, attr)
        if len(meta) < w:
            stdscr.addnstr(row, w - len(meta), meta, len(meta), curses.A_DIM)
        row += 1

    active = _active(data)
    if active:
        sep = height - 7
        stdscr.addnstr(sep, 0, f" live: {active.get('title','')}", w, curses.A_BOLD)
        run_dir = active.get("run_dir", "")
        log = _pick_log(Path(run_dir)) if run_dir else None
        tail = _tail(log, 4) if log else []
        for offset, text in enumerate(tail, start=1):
            if sep + offset < height - 1:
                stdscr.addnstr(sep + offset, 0, "  " + text, w, curses.A_DIM)

    stdscr.addnstr(height - 1, 0, " q quit    refreshing live ".ljust(w), w, curses.A_REVERSE)
    stdscr.refresh()


def _pick_log(run_dir: Path) -> Path | None:
    for name in ("run.jsonl", "run.err", "result.md"):
        candidate = run_dir / name
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None

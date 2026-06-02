"""`guild sessions`: list previous sessions newest first."""
from __future__ import annotations

import argparse
import time

from .. import render, state


def _progress(data: dict) -> str:
    steps = data.get("steps", [])
    done = sum(1 for s in steps if s.get("status") in (state.DONE, state.SKIPPED))
    return f"{done}/{len(steps)}"


def _age(path) -> str:
    try:
        seconds = max(0, int(time.time() - path.stat().st_mtime))
    except OSError:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def session_lines(limit: int = 20) -> list[str]:
    dirs = state.session_dirs()
    if limit > 0:
        dirs = dirs[:limit]
    if not dirs:
        return ["no sessions yet"]

    lines = [f"{render.BOLD}sessions{render.RESET}"]
    for directory in dirs:
        data = state.load_dict(directory / "state.json") or {}
        session_id = str(data.get("id") or directory.name)
        status = str(data.get("status") or "unknown")
        goal = str(data.get("goal") or "").replace("\n", " ")
        if len(goal) > 72:
            goal = goal[:69] + "..."
        lines.append(
            f"  {render.CYAN}{session_id}{render.RESET}  "
            f"{status:9}  {_progress(data):>5}  "
            f"{render.DIM}{_age(directory / 'state.json')} ago{render.RESET}  {goal}"
        )
    return lines


def cmd_sessions(args: argparse.Namespace) -> int:
    for line in session_lines(args.limit):
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("sessions", help="list previous sessions")
    parser.add_argument("-n", "--limit", type=int, default=20,
                        help="maximum sessions to show (default: 20, use 0 for all)")
    parser.set_defaults(func=cmd_sessions, needs_project=True)

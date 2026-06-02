"""`guild sessions`: list previous sessions newest first."""
from __future__ import annotations

import argparse
import time

from .. import render, state


def _progress(data: dict) -> str:
    steps = data.get("steps", [])
    done = sum(1 for s in steps if s.get("status") in (state.DONE, state.SKIPPED))
    return render.progress(done, len(steps), width=10)


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


def _labels(data: dict) -> str:
    labels = data.get("labels", [])
    if not isinstance(labels, list) or not labels:
        return ""
    clean = [str(label).strip() for label in labels if str(label).strip()]
    return f" {render.DIM}[{', '.join(clean)}]{render.RESET}" if clean else ""


def session_lines(limit: int = 20) -> list[str]:
    dirs = state.session_dirs()
    if limit > 0:
        dirs = dirs[:limit]
    if not dirs:
        return ["no sessions yet"]

    lines = [render.banner("guild sessions"), render.kv("showing", f"{len(dirs)} newest")]
    for directory in dirs:
        data = state.load_dict(directory / "state.json") or {}
        session_id = str(data.get("id") or directory.name)
        status = str(data.get("status") or "unknown")
        goal = str(data.get("goal") or "").replace("\n", " ")
        if len(goal) > 72:
            goal = goal[:69] + "..."
        lines.append(
            f"  {render.status_chip(status):17} {render.CYAN}{session_id}{render.RESET}  "
            f"{_progress(data)}  {render.DIM}{_age(directory / 'state.json')} ago{render.RESET}  "
            f"{goal}{_labels(data)}"
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

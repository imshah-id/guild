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


def _clean_labels(data: dict) -> list[str]:
    labels = data.get("labels", [])
    if not isinstance(labels, list):
        return []
    return [str(label).strip().lower() for label in labels if str(label).strip()]


def _search_text(data: dict, session_id: str) -> str:
    parts = [
        session_id,
        str(data.get("status") or ""),
        str(data.get("goal") or ""),
        " ".join(_clean_labels(data)),
    ]
    notes = data.get("notes", [])
    if isinstance(notes, list):
        for note in notes:
            if isinstance(note, dict):
                parts.append(str(note.get("text") or ""))
            else:
                parts.append(str(note))
    steps = data.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                parts.extend([
                    str(step.get("id") or ""),
                    str(step.get("title") or ""),
                    str(step.get("summary") or ""),
                    str(step.get("verdict") or ""),
                ])
    return " ".join(parts).lower()


def _matches(data: dict, session_id: str, *, status: str = "",
             labels: list[str] | None = None, query: str = "") -> bool:
    if status and str(data.get("status") or "").lower() != status.lower():
        return False
    want_labels = [label.lower().lstrip("#") for label in (labels or []) if label]
    have_labels = set(_clean_labels(data))
    if want_labels and not all(label in have_labels for label in want_labels):
        return False
    if query and query.lower() not in _search_text(data, session_id):
        return False
    return True


def session_lines(limit: int = 20, *, status: str = "", labels: list[str] | None = None,
                  query: str = "") -> list[str]:
    dirs = state.session_dirs()
    if not dirs:
        return ["no sessions yet"]

    rows: list[tuple[object, dict]] = []
    for directory in dirs:
        data = state.load_dict(directory / "state.json") or {}
        session_id = str(data.get("id") or directory.name)
        if _matches(data, session_id, status=status, labels=labels, query=query):
            rows.append((directory, data))
    if limit > 0:
        rows = rows[:limit]
    if not rows:
        return ["no sessions match filters"]

    filters: list[str] = []
    if status:
        filters.append(f"status={status}")
    if labels:
        filters.append("label=" + ",".join(labels))
    if query:
        filters.append(f"query={query}")
    detail = f"{len(rows)} newest" + (f" ({'; '.join(filters)})" if filters else "")
    lines = [render.banner("guild sessions"), render.kv("showing", detail)]
    for directory, data in rows:
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
    for line in session_lines(args.limit, status=args.status or "",
                              labels=args.label or [], query=args.query or ""):
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("sessions", help="list previous sessions")
    parser.add_argument("-n", "--limit", type=int, default=20,
                        help="maximum sessions to show (default: 20, use 0 for all)")
    parser.add_argument("--status", choices=[
        "planning", "running", "done", "failed", "blocked", "aborted",
    ], help="show only sessions with this status")
    parser.add_argument("--label", action="append", help="show sessions carrying this label (repeatable)")
    parser.add_argument("-q", "--query", help="search session id, goal, notes, labels, and step summaries")
    parser.set_defaults(func=cmd_sessions, needs_project=True)

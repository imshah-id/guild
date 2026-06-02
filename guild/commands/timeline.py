"""`guild timeline [session]`: show chronological events for a run."""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

from .. import render, state


@dataclass(frozen=True)
class TimelineItem:
    timestamp: float
    order: int
    kind: str
    detail: str
    status: str = ""
    phase: str = ""


def _load_session(session_id: str | None) -> state.Session | None:
    latest = state.latest_session_dir()
    if session_id == "latest":
        session_id = latest.name if latest is not None else None
    if session_id:
        return state.Session.load(session_id)
    if latest is None:
        return None
    return state.Session.load(latest.name)


def _fmt_time(timestamp: float) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp))


def _one_line(text: str, limit: int = 96) -> str:
    value = " ".join(text.strip().split())
    if len(value) <= limit:
        return value
    return value[:limit - 3] + "..."


def _step_result(step: state.Step) -> str:
    if step.verdict:
        return step.verdict
    if step.summary:
        return _one_line(step.summary)
    if step.human_reason:
        return _one_line(step.human_reason)
    return step.title


def timeline_items(session: state.Session) -> list[TimelineItem]:
    items = [
        TimelineItem(session.created, 0, "session", f"created: {_one_line(session.goal)}",
                     status=session.status),
    ]
    order = 1
    for note in session.notes:
        items.append(TimelineItem(note.created or session.created, order, "note", _one_line(note.text)))
        order += 1
    for step in session.steps:
        if step.started:
            agent = f" by {step.agent}" if step.agent else ""
            items.append(TimelineItem(
                step.started,
                order,
                "started",
                f"{step.id} {step.title}{agent}",
                status=state.RUNNING,
                phase=step.phase,
            ))
            order += 1
        else:
            items.append(TimelineItem(
                session.created,
                order,
                "planned",
                f"{step.id} {step.title}",
                status=step.status,
                phase=step.phase,
            ))
            order += 1
        if step.ended:
            items.append(TimelineItem(
                step.ended,
                order,
                "finished",
                f"{step.id} {_step_result(step)}",
                status=step.status,
                phase=step.phase,
            ))
            order += 1
    return sorted(items, key=lambda item: (item.timestamp, item.order))


def timeline_lines(session: state.Session) -> list[str]:
    lines = [
        render.banner("guild timeline"),
        render.kv("session", session.id),
        render.kv("goal", _one_line(session.goal)),
    ]
    if session.labels:
        lines.append(render.kv("labels", ", ".join(session.labels)))
    lines.append("")
    for item in timeline_items(session):
        mark = render.status_mark(item.status) if item.status else "  "
        phase = f"{item.phase:<10}" if item.phase else " " * 10
        lines.append(f"  {_fmt_time(item.timestamp):23} {mark} {item.kind:<8} {phase} {item.detail}")
    return lines


def cmd_timeline(args: argparse.Namespace) -> int:
    session = _load_session(args.session)
    if session is None:
        target = args.session or "latest"
        render.say(f"{render.RED}no such session:{render.RESET} {target}")
        return 1
    for line in timeline_lines(session):
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("timeline", help="show chronological events for a session")
    parser.add_argument("session", nargs="?", help="session id (default: the most recent)")
    parser.set_defaults(func=cmd_timeline, needs_project=True)

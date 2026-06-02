"""`guild report [id]`: render a Markdown summary for a session."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from .. import render, state


def _fmt_time(timestamp: float) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(timestamp))


def _elapsed(step: state.Step) -> str:
    seconds = int(step.elapsed())
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def _clean(text: str) -> str:
    return text.strip() or "-"


def markdown_report(session: state.Session) -> str:
    done = sum(1 for s in session.steps if s.status == state.DONE)
    skipped = sum(1 for s in session.steps if s.status == state.SKIPPED)
    failed = sum(1 for s in session.steps if s.status in (state.FAILED, state.BLOCKED))

    lines = [
        f"# guild report: {session.id}",
        "",
        f"- Goal: {_clean(session.goal)}",
        f"- Status: {session.status}",
        f"- Gating: {session.gating}",
        f"- Created: {_fmt_time(session.created)}",
        f"- Steps: {done} done, {skipped} skipped, {failed} failed/blocked, {len(session.steps)} total",
        "",
    ]
    if session.labels:
        lines.insert(3, f"- Labels: {', '.join(session.labels)}")
    if session.notes:
        lines.extend(["## Notes", ""])
        for note in session.notes:
            lines.append(f"- {_fmt_time(note.created)}: {_clean(note.text)}")
        lines.append("")
    lines.extend(["## Steps", ""])

    for index, step in enumerate(session.steps, start=1):
        title = step.title or step.id
        lines.extend([
            f"### {index}. {title}",
            "",
            f"- Phase: {step.phase}",
            f"- Status: {step.status}",
            f"- Agent: {step.agent or '-'}",
            f"- Elapsed: {_elapsed(step)}",
        ])
        if step.verdict:
            lines.append(f"- Verdict: {step.verdict}")
        if step.run_dir:
            lines.append(f"- Run dir: `{step.run_dir}`")
        if step.changed_files:
            lines.extend(["", "Changed files visible after this step:"])
            lines.extend(f"- `{path}`" for path in step.changed_files)
        if step.diff_stat:
            lines.extend(["", "```text", step.diff_stat, "```"])
        if step.summary:
            lines.extend(["", _clean(step.summary)])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _load_session(session_id: str | None) -> state.Session | None:
    if session_id:
        return state.Session.load(session_id)
    latest = state.latest_session_dir()
    if latest is None:
        return None
    return state.Session.load(latest.name)


def _open_command(path: Path, platform: str = sys.platform) -> list[str]:
    if platform == "darwin":
        return ["open", str(path)]
    if platform.startswith("win"):
        return ["cmd", "/c", "start", "", str(path)]
    return ["xdg-open", str(path)]


def _open_path(path: Path) -> bool:
    try:
        subprocess.Popen(_open_command(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return True


def cmd_report(args: argparse.Namespace) -> int:
    session = _load_session(args.id)
    if session is None:
        target = args.id or "latest"
        render.say(f"{render.RED}no such session:{render.RESET} {target}")
        return 1

    text = markdown_report(session)
    if args.output or args.open:
        path = Path(args.output) if args.output else session.dir / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        render.say(f"wrote {render.CYAN}{path}{render.RESET}")
        if args.open:
            if not _open_path(path):
                render.say(f"{render.RED}could not open report:{render.RESET} no opener available")
                return 1
    else:
        render.out(text.rstrip())
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("report", help="write a Markdown summary for a session")
    parser.add_argument("id", nargs="?", help="session id (default: the most recent)")
    parser.add_argument("-o", "--output", help="write the report to this path instead of stdout")
    parser.add_argument("--open", action="store_true",
                        help="write the report, then open it with the system viewer")
    parser.set_defaults(func=cmd_report, needs_project=True)

"""`guild resume [id]`: continue an interrupted session from where it stopped.

A run can stop short of finishing for many reasons: a timeout, Ctrl-C, the machine sleeping, or
an abort at a gate. The session's state.json already records which steps are done, so resuming
just reloads it and re-enters the pipeline, which skips the completed steps. Steps that were
mid-flight when the run died are reset to pending so they re-run cleanly. Nothing that was
already approved is re-approved: the plan gate is skipped on resume.
"""
from __future__ import annotations

import argparse

from .. import config, render, state
from ..pipeline import Pipeline, PipelineAbort
from .run import _interactive_gate


def _resume_lines(session: state.Session) -> list[str]:
    remaining = [s for s in session.steps if s.status not in (state.DONE, state.SKIPPED)]
    done = len(session.steps) - len(remaining)
    lines = [
        f"{render.BOLD}guild resume{render.RESET}  session {render.CYAN}{session.id}{render.RESET}  "
        f"({session.gating})  {render.DIM}{done}/{len(session.steps)} steps already done{render.RESET}"
    ]
    running = [s for s in remaining if s.status == state.RUNNING]
    if running:
        names = ", ".join(s.title for s in running)
        lines.append(f"{render.YELLOW}interrupted:{render.RESET} {names} will re-run from scratch")
    if remaining:
        next_step = remaining[0]
        lines.append(
            f"{render.DIM}next:{render.RESET} "
            f"{render.phase_color(next_step.phase)}{next_step.phase}{render.RESET} {next_step.title}"
        )
        if len(remaining) > 1:
            lines.append(f"{render.DIM}remaining:{render.RESET} {len(remaining)} steps")
    return lines


def cmd_resume(args: argparse.Namespace) -> int:
    if config.GUILD_DIR is None:
        render.say(f"{render.YELLOW}no project here.{render.RESET} Run `guild init` first.")
        return 1

    session_id = args.id
    if not session_id:
        latest = state.latest_session_dir()
        if latest is None:
            render.say(f"{render.YELLOW}no sessions to resume.{render.RESET}")
            return 1
        session_id = latest.name

    session = state.Session.load(session_id)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {session_id}")
        return 1
    if session.status == "done":
        render.say(f"session {render.CYAN}{session.id}{render.RESET} is already complete.")
        return 0

    remaining = [s for s in session.steps if s.status not in (state.DONE, state.SKIPPED)]
    if not remaining:
        render.say(f"session {render.CYAN}{session.id}{render.RESET} has no remaining steps.")
        return 0

    for line in _resume_lines(session):
        render.say(line)

    # A step left RUNNING was interrupted; reset it to pending so it re-runs from scratch.
    for step in session.steps:
        if step.status == state.RUNNING:
            step.status = state.PENDING
    session.save()

    render.say(f"{render.DIM}watch live in another pane:{render.RESET}  guild monitor")
    render.say(render.rule())

    try:
        Pipeline(session, _interactive_gate, compact=not args.no_compact).run(resume=True)
    except PipelineAbort:
        return 1
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("resume", help="continue an interrupted session where it stopped")
    parser.add_argument("id", nargs="?", help="session id to resume (default: the most recent)")
    parser.add_argument("--no-compact", action="store_true",
                        help="disable token-saving compaction of context fed between agents")
    parser.set_defaults(func=cmd_resume, needs_project=True)

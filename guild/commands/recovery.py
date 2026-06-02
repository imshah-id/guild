"""Targeted recovery commands: `guild retry` and `guild skip`."""
from __future__ import annotations

import argparse

from .. import render, state
from ..pipeline import Pipeline, PipelineAbort
from ._steps import find_step, reset_step
from .run import _interactive_gate


def _generated_from(step_id: str, candidate: state.Step) -> bool:
    return (
        candidate.id.startswith(f"{step_id}-review")
        or candidate.id.startswith(f"{step_id}-fix")
        or candidate.id.startswith(f"{step_id}-retest")
    )


def _load(session_id: str) -> state.Session | None:
    return state.Session.load(session_id)


def _run_if_requested(session: state.Session, args: argparse.Namespace) -> int:
    if not args.run:
        return 0
    try:
        Pipeline(session, _interactive_gate, compact=not args.no_compact).run(resume=True)
    except PipelineAbort:
        return 1
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    session = _load(args.session)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.session}")
        return 1
    found = find_step(session, args.step)
    if found is None:
        render.say(f"{render.RED}no such step:{render.RESET} {args.step}")
        return 1
    _, step = found
    reset_step(step)
    before = len(session.steps)
    session.steps = [s for s in session.steps if s is step or not _generated_from(step.id, s)]
    removed = before - len(session.steps)
    if session.status == "done":
        session.status = "running"
    session.save()
    extra = f" and removed {removed} generated follow-up step(s)" if removed else ""
    render.say(f"{render.GREEN}retry queued{render.RESET} {step.id}{extra}")
    render.say(f"{render.DIM}continue with:{render.RESET} guild resume {session.id}")
    return _run_if_requested(session, args)


def cmd_skip(args: argparse.Namespace) -> int:
    session = _load(args.session)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.session}")
        return 1
    found = find_step(session, args.step)
    if found is None:
        render.say(f"{render.RED}no such step:{render.RESET} {args.step}")
        return 1
    _, step = found
    step.status = state.SKIPPED
    step.started = 0.0
    step.ended = 0.0
    step.returncode = None
    if session.status == "done":
        session.status = "running"
    session.save()
    render.say(f"{render.GREEN}skipped{render.RESET} {step.id}")
    render.say(f"{render.DIM}continue with:{render.RESET} guild resume {session.id}")
    return _run_if_requested(session, args)


def register(subparsers) -> None:
    retry = subparsers.add_parser("retry", help="reset one step so resume re-runs it")
    retry.add_argument("session")
    retry.add_argument("step", help="step index or id")
    retry.add_argument("--run", action="store_true", help="resume immediately after queueing retry")
    retry.add_argument("--no-compact", action="store_true",
                       help="disable token-saving compaction while running")
    retry.set_defaults(func=cmd_retry, needs_project=True)

    skip = subparsers.add_parser("skip", help="mark one step skipped, then resume later")
    skip.add_argument("session")
    skip.add_argument("step", help="step index or id")
    skip.add_argument("--run", action="store_true", help="resume immediately after skipping")
    skip.add_argument("--no-compact", action="store_true",
                      help="disable token-saving compaction while running")
    skip.set_defaults(func=cmd_skip, needs_project=True)

"""`guild plan [id]`: inspect and edit a saved plan before execution."""
from __future__ import annotations

import argparse

from .. import config, render, state, validation
from ..pipeline import Pipeline, PipelineAbort
from ._steps import find_step, plan_lines
from .run import _interactive_gate

_EDITABLE_FIELDS = {"phase", "title", "task", "needs_human", "human_reason", "parallel_group", "depends_on"}


def _load(session_id: str | None) -> state.Session | None:
    if session_id:
        return state.Session.load(session_id)
    latest = state.latest_session_dir()
    return state.Session.load(latest.name) if latest else None


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _set_field(step: state.Step, assignment: str) -> str | None:
    if "=" not in assignment:
        return f"--set expects field=value, got '{assignment}'"
    field, value = assignment.split("=", 1)
    field = field.strip()
    if field not in _EDITABLE_FIELDS:
        return f"field '{field}' is not editable (use: {', '.join(sorted(_EDITABLE_FIELDS))})"
    if field == "phase" and value not in (state.RESEARCH, state.IMPLEMENT, state.TEST):
        return "phase must be research, implement, or test"
    if field == "needs_human":
        setattr(step, field, _parse_bool(value))
    elif field == "depends_on":
        step.depends_on = [item.strip() for item in value.split(",") if item.strip()]
    else:
        setattr(step, field, value.strip())
    return None


def _render_validation(session: state.Session) -> list[validation.PlanIssue]:
    issues = validation.validate_steps(session.steps)
    if not issues:
        render.out("validation ok")
        return issues
    render.out("validation")
    for line in validation.issue_lines(issues):
        render.out(f"  {line}")
    return issues


def _apply_edits(session: state.Session, args: argparse.Namespace) -> str | None:
    for selector in args.drop or []:
        found = find_step(session, selector)
        if found is None:
            return f"no such step: {selector}"
        index, _ = found
        session.steps.pop(index)

    for selector, position in args.move or []:
        found = find_step(session, selector)
        if found is None:
            return f"no such step: {selector}"
        try:
            target = int(position) - 1
        except ValueError:
            return f"move position must be a number, got '{position}'"
        index, step = found
        session.steps.pop(index)
        target = max(0, min(target, len(session.steps)))
        session.steps.insert(target, step)

    for selector, assignment in args.set or []:
        found = find_step(session, selector)
        if found is None:
            return f"no such step: {selector}"
        _, step = found
        error = _set_field(step, assignment)
        if error:
            return error
    return None


def cmd_plan(args: argparse.Namespace) -> int:
    session = _load(args.id)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.id or 'latest'}")
        return 1

    error = _apply_edits(session, args)
    if error:
        render.say(f"{render.RED}{error}{render.RESET}")
        return 1
    if args.drop or args.move or args.set:
        session.status = "planned"
        session.save()
        render.say(f"{render.GREEN}updated plan{render.RESET} {session.id}")

    render.out(f"plan {session.id} [{session.status}]")
    for line in plan_lines(session):
        render.out(line)

    issues: list[validation.PlanIssue] = []
    if args.validate:
        issues = _render_validation(session)

    if args.run:
        if not issues:
            issues = validation.validate_steps(session.steps)
        if validation.has_errors(issues):
            render.say(f"{render.RED}plan has validation errors; not running{render.RESET}")
            return 1
        try:
            Pipeline(session, _interactive_gate, compact=not args.no_compact).run(resume=True)
        except PipelineAbort:
            return 1
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("plan", help="inspect or edit a saved plan")
    parser.add_argument("id", nargs="?", help="session id (default: the most recent)")
    parser.add_argument("--drop", action="append", metavar="STEP",
                        help="remove a step by index or id; can be repeated")
    parser.add_argument("--move", action="append", nargs=2, metavar=("STEP", "POSITION"),
                        help="move a step to a 1-based position")
    parser.add_argument("--set", action="append", nargs=2, metavar=("STEP", "FIELD=VALUE"),
                        help="edit phase, title, task, needs_human, human_reason, parallel_group, or depends_on")
    parser.add_argument("--validate", action="store_true", help="validate dependencies and parallel groups")
    parser.add_argument("--run", action="store_true", help="run the edited plan immediately")
    parser.add_argument("--no-compact", action="store_true",
                        help="disable token-saving compaction while running")
    parser.set_defaults(func=cmd_plan, needs_project=True)

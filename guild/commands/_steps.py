"""Small helpers shared by commands that address a step inside a session."""
from __future__ import annotations

from .. import state


def find_step(session: state.Session, selector: str) -> tuple[int, state.Step] | None:
    """Find a step by 1-based index or exact id."""
    if selector.isdigit():
        index = int(selector) - 1
        if 0 <= index < len(session.steps):
            return index, session.steps[index]
    for index, step in enumerate(session.steps):
        if step.id == selector:
            return index, step
    return None


def reset_step(step: state.Step) -> None:
    step.status = state.PENDING
    step.agent = ""
    step.run_dir = ""
    step.summary = ""
    step.verdict = ""
    step.started = 0.0
    step.ended = 0.0
    step.returncode = None
    step.changed_files = []
    step.diff_stat = ""


def plan_lines(session: state.Session) -> list[str]:
    lines: list[str] = []
    for index, step in enumerate(session.steps, start=1):
        flag = " [needs approval]" if step.needs_human else ""
        group = f" [parallel:{step.parallel_group}]" if step.parallel_group else ""
        deps = f" [depends:{','.join(step.depends_on)}]" if step.depends_on else ""
        lines.append(f"  {index:>2}. {step.id:18} {step.phase:9} {step.status:14} {step.title}{flag}{group}{deps}")
    return lines

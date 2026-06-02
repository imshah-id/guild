"""Plan validation shared by `guild run` and `guild plan`."""
from __future__ import annotations

from dataclasses import dataclass

from . import state

_ALLOWED_PHASES = {state.RESEARCH, state.IMPLEMENT, state.REVIEW, state.TEST, state.FIX}
_TASK_PHASES = {state.RESEARCH, state.IMPLEMENT, state.TEST, state.FIX}


@dataclass(frozen=True)
class PlanIssue:
    level: str
    step_id: str
    message: str


def validate_steps(steps: list[state.Step]) -> list[PlanIssue]:
    issues: list[PlanIssue] = []
    seen: set[str] = set()

    if not steps:
        return [PlanIssue("error", "plan", "plan has no steps")]

    positions = {step.id: index for index, step in enumerate(steps)}
    counts: dict[str, int] = {}
    for step in steps:
        counts[step.id] = counts.get(step.id, 0) + 1

    for index, step in enumerate(steps):
        step_id = step.id or f"step-{index + 1}"
        if not step.id:
            issues.append(PlanIssue("error", step_id, "missing step id"))
        elif step.id in seen:
            issues.append(PlanIssue("error", step.id, "duplicate step id"))
        seen.add(step.id)

        if step.phase not in _ALLOWED_PHASES:
            issues.append(PlanIssue("error", step_id, f"invalid phase '{step.phase}'"))
        if not step.title.strip():
            issues.append(PlanIssue("error", step_id, "missing title"))
        if step.phase in _TASK_PHASES and not step.task.strip():
            issues.append(PlanIssue("error", step_id, "missing task"))
        if step.needs_human and not step.human_reason.strip():
            issues.append(PlanIssue("warn", step_id, "needs_human is set without a human_reason"))

        for dep in step.depends_on:
            if dep == step.id:
                issues.append(PlanIssue("error", step_id, "step depends on itself"))
            elif dep not in positions:
                issues.append(PlanIssue("error", step_id, f"unknown dependency '{dep}'"))
            elif positions[dep] >= index:
                issues.append(PlanIssue("error", step_id, f"dependency '{dep}' must appear before this step"))

    issues.extend(_parallel_group_issues(steps))
    return issues


def _parallel_group_issues(steps: list[state.Step]) -> list[PlanIssue]:
    issues: list[PlanIssue] = []
    groups: dict[str, list[int]] = {}
    for index, step in enumerate(steps):
        if step.parallel_group:
            groups.setdefault(step.parallel_group, []).append(index)
            if step.phase != state.RESEARCH:
                issues.append(PlanIssue("error", step.id, "parallel_group is only supported on research steps"))
            if step.needs_human:
                issues.append(PlanIssue("error", step.id, "parallel research steps cannot require human approval"))

    for group, indexes in groups.items():
        if len(indexes) == 1:
            issues.append(PlanIssue("warn", steps[indexes[0]].id, f"parallel_group '{group}' has only one step"))
        if indexes != list(range(min(indexes), max(indexes) + 1)):
            first = steps[indexes[0]].id
            issues.append(PlanIssue(
                "error", first,
                f"parallel_group '{group}' is split; grouped research steps must be adjacent",
            ))
        member_ids = {steps[i].id for i in indexes}
        for index in indexes:
            step = steps[index]
            for dep in step.depends_on:
                if dep in member_ids:
                    issues.append(PlanIssue("error", step.id, "parallel steps cannot depend on each other"))

    return issues


def has_errors(issues: list[PlanIssue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def issue_lines(issues: list[PlanIssue]) -> list[str]:
    return [f"{issue.level}: {issue.step_id}: {issue.message}" for issue in issues]

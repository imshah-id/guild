"""Planning: ask the planner agent (read-only) to decompose a goal into steps."""
from __future__ import annotations

import json
import re

from . import agents, config, prompts, roles, state


class PlanError(RuntimeError):
    """Raised when planning fails or its output cannot be parsed into valid steps."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text)


def make_plan(session: state.Session) -> list[state.Step]:
    spec = roles.spec_for("planner")
    prompt = agents.assemble(
        roles.brief_for("planner"),
        prompts.PLANNER_INSTRUCTIONS + f"\n\n## Goal\n\n{session.goal}\n",
    )
    run_dir = session.dir / "00-plan"
    result = agents.run(spec, roles.READ_ONLY, prompt, run_dir, timeout=config.PLANNER_TIMEOUT_SECONDS)
    if not result.ok:
        raise PlanError(f"planner call failed (rc={result.returncode}); see {run_dir}/run.err")
    try:
        data = _extract_json(result.text)
    except json.JSONDecodeError as exc:
        raise PlanError(f"could not parse plan JSON: {exc}; see {run_dir}/result.md") from exc

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanError("plan contained no steps")

    steps: list[state.Step] = []
    for index, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            continue
        phase = str(raw.get("phase", "")).strip()
        if phase not in (state.RESEARCH, state.IMPLEMENT, state.TEST):
            continue
        title = (str(raw.get("title", phase)).strip() or phase)[:80]
        steps.append(
            state.Step(
                id=f"{index:02d}-{phase}",
                phase=phase,
                title=title,
                task=str(raw.get("task", "")).strip(),
                needs_human=bool(raw.get("needs_human", False)),
                human_reason=str(raw.get("human_reason", "")).strip(),
                parallel_group=str(raw.get("parallel_group", "")).strip(),
            )
        )
    if not steps:
        raise PlanError("plan had no valid steps after validation")
    return steps

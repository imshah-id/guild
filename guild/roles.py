"""Abstract roles and how they map onto concrete agents.

A role is what the work needs done (plan, research, implement, review, test). An agent is a
concrete CLI (claude, codex, agy). The mapping lives in config, so you can swap which CLI plays
which role without touching code. Each role carries a *capability* (read-only or write); the
agent adapter applies the matching permission posture from the capability, not from the agent's
identity, so e.g. a coder mapped to `claude` may edit while a reviewer mapped to `codex` stays
read-only.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config, prompts

READ_ONLY = "read-only"
WRITE = "write"

# Role -> capability. Planning, research and review never edit; implementation and tests do.
ROLE_CAPABILITY: dict[str, str] = {
    "planner": READ_ONLY,
    "researcher": READ_ONLY,
    "implementer": WRITE,
    "reviewer": READ_ONLY,
    "tester": WRITE,
}
ROLES = tuple(ROLE_CAPABILITY)

# Role -> the scorecard phase its outcomes are recorded under. Used to rank candidate agents for
# a role by how well they have done that kind of work before.
ROLE_PHASE: dict[str, str] = {
    "planner": "plan",
    "researcher": "research",
    "implementer": "implement",
    "reviewer": "review",
    "tester": "test",
}

# Roles a `guild run` cannot proceed without (research is optional; a plan may have no research).
REQUIRED_ROLES = ("planner", "implementer", "reviewer", "tester")


class RoleError(RuntimeError):
    """Raised when a role maps to an agent that is not in the roster."""


@dataclass
class AgentSpec:
    name: str                  # roster key, e.g. "claude"
    bin: str                   # executable, e.g. "claude"
    adapter: str               # which adapter builds the command: "claude" | "codex" | "agy"
    model: str | None = None
    effort: str | None = None
    sandbox: str = "workspace-write"


@dataclass
class Assignment:
    """The agent chosen to play a role for a step, plus why if it was a substitution.

    `spec` is the agent that will run. `fallback_from` names the configured agent we could not
    use as-is (None when the configured agent was used directly), and `reason` explains the
    substitution in one human-readable phrase for an honest routing notice.
    """
    spec: AgentSpec
    fallback_from: str | None = None
    reason: str = ""

    @property
    def substituted(self) -> bool:
        """True when a different agent than the configured one is actually running."""
        return self.fallback_from is not None and self.fallback_from != self.spec.name


def roster() -> dict[str, dict]:
    return config.setting("agents", {}) or {}


def agent_names() -> list[str]:
    return list(roster().keys())


def spec_for_agent(name: str) -> AgentSpec:
    entry = roster().get(name)
    if not isinstance(entry, dict):
        raise RoleError(f"agent '{name}' is not defined in config.agents")
    return AgentSpec(
        name=name,
        bin=str(entry.get("bin", name)),
        adapter=str(entry.get("adapter", name)),
        model=entry.get("model"),
        effort=entry.get("effort"),
        sandbox=str(entry.get("sandbox", "workspace-write")),
    )


def agent_for_role(role: str) -> str:
    name = config.setting(f"roles.{role}")
    if not name:
        raise RoleError(f"no agent configured for role '{role}'")
    return str(name)


def capability_for(role: str) -> str:
    return ROLE_CAPABILITY.get(role, READ_ONLY)


def spec_for(role: str) -> AgentSpec:
    return spec_for_agent(agent_for_role(role))


def brief_for(role: str) -> str:
    """Project role-brief override (`.guild/roles/<role>.md`) if present, else the built-in."""
    project_dir = config.PROJECT_ROLES_DIR
    if project_dir is not None:
        override = project_dir / f"{role}.md"
        try:
            text = override.read_text()
            if text.strip():
                return text
        except OSError:
            pass
    return prompts.ROLE_BRIEFS.get(role, prompts.ROLE_BRIEFS["implementer"])


def _on_path(name: str) -> bool:
    import shutil

    spec = roster().get(name) or {}
    return shutil.which(str(spec.get("bin", name))) is not None


def installed(name: str) -> bool:
    """Public: is the agent's binary on PATH?"""
    return _on_path(name)


# --- scorecard-aware ranking -------------------------------------------------------------

def _smoothed_rate(ok: int, total: int) -> float:
    """Laplace-smoothed success rate. An untried agent sits at a neutral 0.5, and a handful of
    samples nudge the estimate gently instead of swinging it to a noisy 0.0 or 1.0."""
    return (ok + 1) / (total + 2)


def _agent_score(name: str, phase: str, agents_data: dict) -> tuple[float, float]:
    """(success rate for this phase, overall success rate) from the scorecard, both smoothed."""
    item = agents_data.get(name, {}) if isinstance(agents_data, dict) else {}
    if not isinstance(item, dict):
        item = {}
    phases = item.get("phases", {})
    pdata = phases.get(phase, {}) if isinstance(phases, dict) else {}
    if not isinstance(pdata, dict):
        pdata = {}
    phase_rate = _smoothed_rate(int(pdata.get("ok", 0)), int(pdata.get("total", 0)))
    overall_rate = _smoothed_rate(int(item.get("ok", 0)), int(item.get("total", 0)))
    return (phase_rate, overall_rate)


def rank_candidates(names: list[str], phase: str) -> list[str]:
    """Order `names` best-first by scorecard success rate for `phase`, then overall rate, with
    the given (roster) order as a stable tie-break so an untried roster keeps its declared
    order. Reading the scorecard is best-effort; if it is unavailable everyone ties and order is
    preserved."""
    if len(names) <= 1:
        return list(names)
    from . import scorecard  # local import keeps roles free of a scorecard dependency at import

    agents_data = scorecard.load().get("agents", {})
    indexed = list(enumerate(names))
    indexed.sort(key=lambda pair: (*_agent_score(pair[1], phase, agents_data), -pair[0]), reverse=True)
    return [name for _, name in indexed]


# --- assignment --------------------------------------------------------------------------

def resolve_role(role: str, *, exclude: set[str] | None = None) -> Assignment:
    """Pick a concrete agent to play `role`, preferring one that is actually installed.

    The configured agent wins when it is installed and not excluded: an explicit choice is
    respected, never second-guessed by the scorecard. Only when the configured agent is missing
    or excluded do we substitute, choosing the best-performing *installed* alternative (scorecard,
    then roster order). With no installed alternative we fall back to the best remaining candidate
    so the run can still proceed exactly as before (it may then fail at call time, but cross-review
    stays independent). Raises RoleError only when the role has no agent configured at all.
    """
    exclude = set(exclude or ())
    configured = agent_for_role(role)        # raises RoleError if the role is unmapped
    phase = ROLE_PHASE.get(role, role)

    if configured not in exclude and _on_path(configured):
        return Assignment(spec_for_agent(configured))

    candidates = [n for n in agent_names() if n not in exclude]
    installed_candidates = rank_candidates([n for n in candidates if _on_path(n)], phase)
    if installed_candidates:
        reason = ("configured agent is the author"
                  if configured in exclude else f"'{configured}' is not installed")
        return Assignment(spec_for_agent(installed_candidates[0]), fallback_from=configured, reason=reason)

    # Nothing installed. Keep the configured agent if it is a usable candidate (status quo).
    if configured not in exclude:
        return Assignment(spec_for_agent(configured))

    # Configured agent is excluded and nothing is installed: still substitute another agent so
    # the review stays independent, even though it may not be installed.
    other = rank_candidates(candidates, phase)
    if other:
        return Assignment(spec_for_agent(other[0]), fallback_from=configured,
                          reason="substituted to keep the review independent")

    # Single-agent setup: only the excluded agent exists. Fall back to it; review is a second
    # pass, not an independent one.
    return Assignment(spec_for_agent(configured), fallback_from=configured,
                      reason="only one agent configured; review is a second pass, not independent")


def reviewer_assignment(author_agent: str) -> Assignment:
    """The cross-review rule, with routing: a change must be reviewed by a different agent than
    wrote it. Resolves the reviewer role while excluding the author."""
    return resolve_role("reviewer", exclude={author_agent})


def reviewer_spec(author_agent: str) -> AgentSpec:
    """Back-compat thin wrapper over `reviewer_assignment` for callers that only want the spec."""
    return reviewer_assignment(author_agent).spec


def availability_issues(required: tuple[str, ...] = REQUIRED_ROLES) -> list[str]:
    """Problems that should stop a run before it starts: a required role whose configured agent
    is not installed and that has no installed alternative either. Empty list means good to go."""
    issues: list[str] = []
    for role in required:
        try:
            configured = agent_for_role(role)
        except RoleError as exc:
            issues.append(f"{role}: {exc}")
            continue
        if _on_path(configured):
            continue
        alternatives = [n for n in agent_names() if n != configured and _on_path(n)]
        if not alternatives:
            issues.append(
                f"{role}: configured agent '{configured}' is not on PATH and no other agent is "
                f"installed (install it, or `guild config set roles.{role} <agent>`)"
            )
    return issues


def cross_review_conflict() -> str | None:
    """For `doctor`/`status`: warn if reviewer and implementer resolve to the same agent."""
    try:
        if agent_for_role("reviewer") == agent_for_role("implementer"):
            return agent_for_role("reviewer")
    except RoleError:
        return None
    return None

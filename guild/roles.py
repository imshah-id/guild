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


def reviewer_spec(author_agent: str) -> AgentSpec:
    """The cross-review rule: a change must be reviewed by a different agent than wrote it.
    Returns the configured reviewer unless it is the author, in which case it substitutes a
    different agent (preferring one that is installed), so review is always independent."""
    configured = agent_for_role("reviewer")
    if configured != author_agent:
        return spec_for_agent(configured)
    alternatives = [n for n in agent_names() if n != author_agent]
    if not alternatives:
        # Only one agent exists; fall back to it (review is at least a second pass).
        return spec_for_agent(author_agent)
    preferred = next((n for n in alternatives if _on_path(n)), alternatives[0])
    return spec_for_agent(preferred)


def cross_review_conflict() -> str | None:
    """For `doctor`/`status`: warn if reviewer and implementer resolve to the same agent."""
    try:
        if agent_for_role("reviewer") == agent_for_role("implementer"):
            return agent_for_role("reviewer")
    except RoleError:
        return None
    return None

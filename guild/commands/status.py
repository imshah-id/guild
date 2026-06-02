"""`guild status`: a one-screen overview of the resolved setup and the latest session."""
from __future__ import annotations

import argparse
import shutil

from .. import config, render, roles, state

_ROLE_CHIP = {
    "planner": ("PLAN", state.PLAN),
    "researcher": ("RESEARCH", state.RESEARCH),
    "implementer": ("IMPLEMENT", state.IMPLEMENT),
    "reviewer": ("REVIEW", state.REVIEW),
    "tester": ("TEST", state.TEST),
}


def _agent_descr(name: str) -> str:
    try:
        spec = roles.spec_for_agent(name)
    except roles.RoleError:
        return name
    bits = [name]
    if spec.model:
        bits.append(f"model={spec.model}")
    if spec.effort:
        bits.append(f"effort={spec.effort}")
    return "  ".join(bits)


def status_lines() -> list[str]:
    lines: list[str] = []
    lines.append(render.banner("guild status"))

    if config.GUILD_DIR is not None:
        lines.append(render.kv("project", config.PROJECT_ROOT))
        ctx = "ok" if (config.CONTEXT_PATH and config.CONTEXT_PATH.exists()) else "missing (edit it)"
        lines.append(render.kv("context", f"{config.PROJECT_DIRNAME}/context.md  {render.DIM}{ctx}{render.RESET}"))
    else:
        lines.append(render.kv("project", f"{render.YELLOW}not initialized here{render.RESET}  "
                               f"{render.DIM}(run `guild init`){render.RESET}"))

    lines.append("")
    lines.append(render.section("roles -> agent"))
    for role in roles.ROLES:
        try:
            agent = roles.agent_for_role(role)
            cap = roles.capability_for(role)
            label, phase = _ROLE_CHIP.get(role, (role.upper()[:9], ""))
            lines.append(f"  {render.chip(label.ljust(9), color=render.phase_color(phase))} {role:12} "
                         f"{render.CYAN}{_agent_descr(agent)}{render.RESET}  {render.DIM}{cap}{render.RESET}")
        except roles.RoleError as exc:
            lines.append(f"  {render.status_mark('failed')} {role:12} {render.RED}{exc}{render.RESET}")

    conflict = roles.cross_review_conflict()
    if conflict:
        lines.append(f"  {render.status_mark('needs_approval')} reviewer and implementer are both "
                     f"'{conflict}'; reviews auto-substitute a different agent")

    lines.append("")
    lines.append(render.section("runtime"))
    lines.append(render.kv("gating", f"{render.CYAN}{config.setting('gating')}{render.RESET}"))
    comp = config.setting("compaction", {}) or {}
    lines.append(render.kv("compaction", f"{'on' if comp.get('enabled') else 'off'}  "
                           f"{render.DIM}(toggle: guild config set compaction.enabled false){render.RESET}"))

    lines.append("")
    lines.append(render.section("agents on PATH"))
    for name in roles.agent_names():
        try:
            binary = roles.spec_for_agent(name).bin
        except roles.RoleError:
            binary = name
        mark = render.status_mark("done") if shutil.which(binary) else render.status_mark("failed")
        lines.append(f"  {mark} {name:8} {render.DIM}({binary}){render.RESET}")

    latest = state.latest_session_dir()
    lines.append("")
    if latest is not None:
        data = state.load_dict(latest / "state.json") or {}
        steps = data.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        lines.append(render.section("latest session", str(data.get("id", ""))))
        lines.append(render.kv("state", f"{render.status_chip(str(data.get('status','')))} "
                               f"{render.progress(done, len(steps))}"))
        lines.append(render.kv("goal", f"{render.DIM}{str(data.get('goal',''))[:70]}{render.RESET}"))
        lines.append(render.kv("watch", "guild monitor"))
    else:
        lines.append(render.kv("sessions", f"{render.DIM}none yet{render.RESET}"))
    return lines


def cmd_status(args: argparse.Namespace) -> int:
    for line in status_lines():
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("status", help="show resolved roles, agents, gating, and the latest session")
    parser.set_defaults(func=cmd_status, needs_project=False)

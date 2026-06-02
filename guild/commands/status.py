"""`guild status`: a one-screen overview of the resolved setup and the latest session."""
from __future__ import annotations

import argparse
import shutil

from .. import config, render, roles, state


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
    lines.append(f"{render.BOLD}guild{render.RESET}")

    if config.GUILD_DIR is not None:
        lines.append(f"  project   {config.PROJECT_ROOT}")
        ctx = "ok" if (config.CONTEXT_PATH and config.CONTEXT_PATH.exists()) else "missing (edit it)"
        lines.append(f"  context   {config.PROJECT_DIRNAME}/context.md  {render.DIM}{ctx}{render.RESET}")
    else:
        lines.append(f"  project   {render.YELLOW}not initialized here{render.RESET}  "
                     f"{render.DIM}(run `guild init`){render.RESET}")

    lines.append("")
    lines.append(f"  {render.BOLD}roles -> agent{render.RESET}")
    for role in roles.ROLES:
        try:
            agent = roles.agent_for_role(role)
            cap = roles.capability_for(role)
            lines.append(f"    {role:12} {render.CYAN}{_agent_descr(agent)}{render.RESET}  "
                         f"{render.DIM}{cap}{render.RESET}")
        except roles.RoleError as exc:
            lines.append(f"    {role:12} {render.RED}{exc}{render.RESET}")

    conflict = roles.cross_review_conflict()
    if conflict:
        lines.append(f"    {render.YELLOW}! reviewer and implementer are both '{conflict}'; "
                     f"reviews auto-substitute a different agent{render.RESET}")

    lines.append("")
    lines.append(f"  gating    {render.CYAN}{config.setting('gating')}{render.RESET}")
    comp = config.setting("compaction", {}) or {}
    lines.append(f"  compaction {'on' if comp.get('enabled') else 'off'}  "
                 f"{render.DIM}(toggle: guild config set compaction.enabled false){render.RESET}")

    lines.append("")
    lines.append(f"  {render.BOLD}agents on PATH{render.RESET}")
    for name in roles.agent_names():
        try:
            binary = roles.spec_for_agent(name).bin
        except roles.RoleError:
            binary = name
        mark = f"{render.GREEN}ok  {render.RESET}" if shutil.which(binary) else f"{render.RED}MISS{render.RESET}"
        lines.append(f"    {mark} {name:8} ({binary})")

    latest = state.latest_session_dir()
    lines.append("")
    if latest is not None:
        data = state.load_dict(latest / "state.json") or {}
        steps = data.get("steps", [])
        done = sum(1 for s in steps if s.get("status") == "done")
        lines.append(f"  {render.BOLD}latest session{render.RESET}  {data.get('id','')}  "
                     f"[{data.get('status','')}]  {done}/{len(steps)} steps")
        lines.append(f"    {render.DIM}goal: {str(data.get('goal',''))[:70]}{render.RESET}")
        lines.append(f"    {render.DIM}watch: guild monitor{render.RESET}")
    else:
        lines.append(f"  {render.DIM}no sessions yet{render.RESET}")
    return lines


def cmd_status(args: argparse.Namespace) -> int:
    for line in status_lines():
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("status", help="show resolved roles, agents, gating, and the latest session")
    parser.set_defaults(func=cmd_status, needs_project=False)

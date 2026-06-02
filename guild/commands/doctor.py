"""`guild doctor`: check that the configured agent CLIs are installed, and validate config."""
from __future__ import annotations

import argparse
import shutil
import subprocess

from .. import config, render, roles


def _ping(cmd: list[str], *, last_line: bool = False) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                             cwd=str(config.PROJECT_ROOT))
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"(error: {exc})"
    text = out.stdout.strip()
    if last_line and text:
        text = text.splitlines()[-1]
    return text[:40] if text else "(no output)"


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    render.out(f"{render.BOLD}agents{render.RESET}")
    present: dict[str, str] = {}
    for name in roles.agent_names():
        try:
            spec = roles.spec_for_agent(name)
        except roles.RoleError as exc:
            render.out(f"  {render.RED}bad {render.RESET} {name}: {exc}")
            ok = False
            continue
        if shutil.which(spec.bin):
            present[name] = spec.bin
            render.out(f"  {render.GREEN}ok  {render.RESET} {name:8} {spec.adapter} adapter ({spec.bin})")
        else:
            render.out(f"  {render.RED}MISS{render.RESET} {name:8} {spec.bin} not on PATH")
            ok = False

    render.out("")
    render.out(f"{render.BOLD}config{render.RESET}")
    conflict = roles.cross_review_conflict()
    if conflict:
        render.out(f"  {render.YELLOW}warn{render.RESET} reviewer == implementer ('{conflict}'); "
                   "cross-review will substitute a different agent")
    else:
        render.out(f"  {render.GREEN}ok  {render.RESET} cross-review: reviewer differs from implementer")

    if args.live and present:
        render.out("")
        render.out(f"{render.BOLD}live ping{render.RESET} {render.DIM}(one tiny prompt each, costs a call){render.RESET}")
        for name, binary in present.items():
            adapter = roles.spec_for_agent(name).adapter
            if adapter == "claude":
                render.out(f"  {name}: {_ping([binary, '-p', 'reply with the single word ok'])}")
            elif adapter == "codex":
                render.out(f"  {name}: {_ping([binary, 'exec', '-s', 'read-only', '--skip-git-repo-check', 'reply with the single word ok'], last_line=True)}")
            elif adapter == "agy":
                render.out(f"  {name}: {_ping([binary, '--print', '--print-timeout', '60s', 'reply with the single word ok'])}")
    return 0 if ok else 1


def register(subparsers) -> None:
    parser = subparsers.add_parser("doctor", help="check the configured agent CLIs and config")
    parser.add_argument("--live", action="store_true", help="also ping each agent (costs a call)")
    parser.set_defaults(func=cmd_doctor, needs_project=False)

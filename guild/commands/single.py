"""Single-agent one-offs: `guild research|implement|test|review "<task>" [paths...]`.

These run one role once, with no pipeline, no auto-review, and no fix loop. Useful for a quick
question or a focused change you will review yourself.
"""
from __future__ import annotations

import argparse
import time

from .. import agents, config, render, roles

# command name -> role
_ROLE = {
    "research": "researcher",
    "implement": "implementer",
    "test": "tester",
    "review": "reviewer",
}


def _make(name: str):
    def cmd(args: argparse.Namespace) -> int:
        if config.GUILD_DIR is None:
            render.say(f"{render.YELLOW}no project here.{render.RESET} Run `guild init` first.")
            return 1
        role = _ROLE[name]
        task = args.task
        if args.paths:
            task = f"{task}\n\nPaths to focus on: {' '.join(args.paths)}"
        run_dir = config.RUNS_DIR / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{name}"
        spec = roles.spec_for(role)
        render.say(f"{render.BOLD}{name}{render.RESET} -> {spec.name}  {render.DIM}({run_dir}){render.RESET}")
        with render.Spinner(f"{name} running"):
            result = agents.run_role(role, task, run_dir, timeout=config.STEP_TIMEOUT_SECONDS)
        render.say(render.rule())
        render.out(result.text if result.text.strip() else f"(no output; see {run_dir}/run.err)")
        render.say(render.rule())
        return 0 if result.ok else 1

    return cmd


def register(subparsers) -> None:
    for name in _ROLE:
        parser = subparsers.add_parser(name, help=f"one-off {name} (single agent, no pipeline)")
        parser.add_argument("task")
        parser.add_argument("paths", nargs="*")
        parser.set_defaults(func=_make(name), needs_project=True)

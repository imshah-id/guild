"""guild: run your installed AI coding CLIs as a coordinated team.

  guild init [--analyze]              bootstrap .guild/ for the current project
  guild status                        resolved roles, agents, gating, latest session
  guild run "<goal>"                  autonomous: plan, build, cross-review, test, report
  guild plan [id]                     inspect or edit a saved plan
  guild sessions                      list previous sessions
  guild report [id]                   write a Markdown summary for a session
  guild resume [id]                   continue an interrupted session where it stopped
  guild retry <id> <step>             reset one step so resume re-runs it
  guild skip <id> <step>              mark one step skipped
  guild monitor [id]                  live dashboard for a session
  guild config set roles.reviewer codex      toggle any setting
  guild research|implement|test|review "<task>" [paths...]   single-agent one-offs
  guild doctor [--live]               check the configured agent CLIs
"""
from __future__ import annotations

import argparse

from . import __version__, config, home
from .commands import (
    completion, config_cmd, doctor, init, monitor, plan, recovery, report, resume, run,
    scorecard_cmd, sessions, single, status,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guild",
        description="Run your installed AI coding CLIs as a team: one plans and reviews, "
                    "others implement, test, and research. No model APIs; the CLIs are driven "
                    "as subprocesses and coordinated through files.",
    )
    parser.add_argument("--version", action="version", version=f"guild {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")

    # Order here is the order shown in --help.
    init.register(sub)
    status.register(sub)
    run.register(sub)
    plan.register(sub)
    sessions.register(sub)
    report.register(sub)
    resume.register(sub)
    recovery.register(sub)
    monitor.register(sub)
    config_cmd.register(sub)
    single.register(sub)
    doctor.register(sub)
    scorecard_cmd.register(sub)
    completion.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config.activate()  # discover the project (if any) and load merged settings
    if not getattr(args, "cmd", None):
        home.open_home()
        return 0
    return int(args.func(args))

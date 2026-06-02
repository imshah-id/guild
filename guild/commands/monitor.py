"""`guild monitor`: live, read-only dashboard for a session (defaults to the latest)."""
from __future__ import annotations

import argparse
from pathlib import Path

from .. import config, monitor, render, state


def cmd_monitor(args: argparse.Namespace) -> int:
    if args.session:
        session_dir: Path | None = config.RUNS_DIR / args.session
    else:
        session_dir = state.latest_session_dir()
    if session_dir is None or not (session_dir / "state.json").exists():
        render.say("no session to monitor yet (run `guild run \"...\"` first)")
        return 1
    monitor.watch(session_dir / "state.json")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("monitor", help="live dashboard for a session (defaults to the latest)")
    parser.add_argument("session", nargs="?")
    parser.set_defaults(func=cmd_monitor, needs_project=True)

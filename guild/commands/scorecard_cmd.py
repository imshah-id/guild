"""`guild scorecard`: show lightweight per-agent run outcomes."""
from __future__ import annotations

import argparse
import json

from .. import render, scorecard


def cmd_scorecard(args: argparse.Namespace) -> int:
    data = scorecard.load()
    if args.json:
        render.out(json.dumps(data, indent=2))
        return 0
    for line in scorecard.lines(data):
        render.out(line)
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("scorecard", help="show per-agent outcome stats")
    parser.add_argument("--json", action="store_true", help="print raw scorecard JSON")
    parser.set_defaults(func=cmd_scorecard, needs_project=True)

"""`guild config`: read and toggle settings without hand-editing JSON.

  guild config list                 show the merged config and where each value came from
  guild config get roles.reviewer   print one resolved value
  guild config set roles.reviewer codex      [--global]
  guild config set agents.codex.model gpt-5.5
  guild config set gating hands-off
  guild config unset agents.codex.model        [--global]

Writes the project config (.guild/config.json) by default, or the global user config with
--global.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import config, render


def _target_path(use_global: bool) -> Path | None:
    if use_global:
        return config.global_config_path()
    if config.GUILD_DIR is None:
        return None
    return config.GUILD_DIR / "config.json"


def _walk_leaves(node: dict, prefix: str = ""):
    for key, value in node.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _walk_leaves(value, f"{dotted}.")
        else:
            yield dotted, value


def cmd_config(args: argparse.Namespace) -> int:
    action = args.action

    if action == "list":
        render.out(f"global:  {config.global_config_path()}")
        render.out(f"project: {(config.GUILD_DIR / 'config.json') if config.GUILD_DIR else '(no project; run guild init)'}")
        render.out("")
        for dotted, value in _walk_leaves(config.SETTINGS):
            source = config.SOURCES.get(dotted, "default")
            render.out(f"  {dotted:32} = {json.dumps(value):20} {render.DIM}[{source}]{render.RESET}")
        return 0

    if action == "get":
        if not args.key:
            render.say("usage: guild config get <key>")
            return 1
        value = config.setting(args.key, _MISSING)
        if value is _MISSING:
            render.say(f"{render.YELLOW}no such key:{render.RESET} {args.key}")
            return 1
        render.out(json.dumps(value))
        return 0

    target = _target_path(args.use_global)
    if target is None:
        render.say(f"{render.YELLOW}no project here.{render.RESET} Run `guild init`, or use --global.")
        return 1

    if action == "set":
        if not args.key or args.value is None:
            render.say("usage: guild config set <key> <value> [--global]")
            return 1
        value = config.parse_value(args.value)
        config.write_setting(target, args.key, value)
        render.say(f"{render.GREEN}set{render.RESET} {args.key} = {json.dumps(value)}  "
                   f"{render.DIM}in {target}{render.RESET}")
        return 0

    if action == "unset":
        if not args.key:
            render.say("usage: guild config unset <key> [--global]")
            return 1
        if config.unset_setting(target, args.key):
            render.say(f"{render.GREEN}unset{render.RESET} {args.key}  {render.DIM}in {target}{render.RESET}")
            return 0
        render.say(f"{render.YELLOW}{args.key} was not set in {target}{render.RESET}")
        return 1

    render.say("usage: guild config <list|get|set|unset> ...")
    return 1


_MISSING = object()


def register(subparsers) -> None:
    parser = subparsers.add_parser("config", help="read and toggle settings (roles, models, gating, ...)")
    parser.add_argument("action", choices=["list", "get", "set", "unset"])
    parser.add_argument("key", nargs="?")
    parser.add_argument("value", nargs="?")
    parser.add_argument("--global", dest="use_global", action="store_true",
                        help="target the global user config instead of the project")
    parser.set_defaults(func=cmd_config, needs_project=False)

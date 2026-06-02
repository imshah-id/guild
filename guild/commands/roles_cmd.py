"""`guild roles`: see and change which agent plays each role.

  guild roles                     show every role, its agent, capability, and availability
  guild roles set reviewer codex  reassign one role            [--global]
  guild roles edit                walk through every role interactively   [--global]
  guild roles reset               restore the default assignment          [--global]

A thin, discoverable front door over `roles.*` in the config. Writes the project config
(.guild/config.json) by default, or the global user config with --global. The same cross-review
rule still applies at run time: a review is always routed to a different agent than the author.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .. import config, prompt, render, roles


def _target_path(use_global: bool) -> Path | None:
    if use_global:
        return config.global_config_path()
    if config.GUILD_DIR is None:
        return None
    return config.GUILD_DIR / "config.json"


def _role_line(role: str) -> str:
    cap = roles.capability_for(role)
    try:
        assignment = roles.resolve_role(role)
    except roles.RoleError as exc:
        return f"  {render.status_mark('failed')} {role:12} {render.RED}{exc}{render.RESET}"
    configured = roles.agent_for_role(role)
    resolved = assignment.spec.name
    mark = render.status_mark("done") if roles.installed(resolved) else render.status_mark("failed")
    note = f"  {render.DIM}{cap}{render.RESET}"
    if assignment.fallback_from:
        note += f"  {render.YELLOW}-> {resolved} ({assignment.reason}){render.RESET}"
    elif not roles.installed(resolved):
        note += f"  {render.RED}(not on PATH){render.RESET}"
    return f"  {mark} {role:12} {render.CYAN}{configured}{render.RESET}{note}"


def _list() -> int:
    in_project = config.GUILD_DIR is not None
    where = str(config.GUILD_DIR / "config.json") if in_project else "built-in defaults (no project here)"
    render.out(render.banner("guild roles", ("config", where)))
    render.out("")
    for role in roles.ROLES:
        render.out(_role_line(role))
    conflict = roles.cross_review_conflict()
    if conflict:
        render.out("")
        render.out(f"  {render.status_mark('needs_approval')} reviewer and implementer are both "
                   f"'{conflict}'; reviews auto-substitute a different agent")
    render.out("")
    if not in_project:
        render.out(f"  {render.YELLOW}no .guild/ project here, so changes have nowhere to go.{render.RESET}")
        render.out(f"  {render.DIM}`guild init` to create one, then `guild roles set <role> <agent>` "
                   f"-- or add --global to edit your user-wide config.{render.RESET}")
    else:
        render.out(f"  {render.DIM}change with: guild roles set <role> <agent>   "
                   f"(roles: {', '.join(roles.ROLES)}){render.RESET}")
    render.out(f"  {render.DIM}agents: {', '.join(roles.agent_names())}{render.RESET}")
    return 0


def _validate(role: str, agent: str) -> str | None:
    if role not in roles.ROLES:
        return f"unknown role '{role}' (roles: {', '.join(roles.ROLES)})"
    if agent not in roles.agent_names():
        return f"unknown agent '{agent}' (agents: {', '.join(roles.agent_names())})"
    return None


def _write(target: Path, role: str, agent: str) -> None:
    config.write_setting(target, f"roles.{role}", agent)
    note = "" if roles.installed(agent) else f"  {render.YELLOW}(not on PATH yet){render.RESET}"
    render.say(f"{render.GREEN}set{render.RESET} {role} -> {render.CYAN}{agent}{render.RESET}{note}"
               f"  {render.DIM}in {target}{render.RESET}")


def cmd_roles(args: argparse.Namespace) -> int:
    action = args.action or "list"

    if action == "list":
        return _list()

    target = _target_path(args.use_global)
    if target is None:
        hint = f"guild roles {action}"
        if action == "set" and args.role and args.agent:
            hint = f"guild roles set {args.role} {args.agent}"
        render.say(f"{render.YELLOW}no .guild/ project in this directory.{render.RESET}")
        render.say(f"  {render.DIM}cd into your project and `guild init`, or set it user-wide:{render.RESET}")
        render.say(f"  {render.CYAN}{hint} --global{render.RESET}")
        return 1

    if action == "set":
        if not args.role or not args.agent:
            render.say("usage: guild roles set <role> <agent> [--global]")
            return 1
        error = _validate(args.role, args.agent)
        if error:
            render.say(f"{render.RED}{error}{render.RESET}")
            return 1
        _write(target, args.role, args.agent)
        return 0

    if action == "reset":
        for role, agent in config.DEFAULTS["roles"].items():
            config.write_setting(target, f"roles.{role}", agent)
        render.say(f"{render.GREEN}reset{render.RESET} roles to defaults  {render.DIM}in {target}{render.RESET}")
        return 0

    if action == "edit":
        if not prompt.interactive():
            render.say(f"{render.YELLOW}not a terminal;{render.RESET} use `guild roles set <role> <agent>`")
            return 1
        agent_options = roles.agent_names()
        agent_desc = {name: (f"{render.GREEN}installed{render.RESET}" if roles.installed(name)
                             else f"{render.RED}not on PATH{render.RESET}") for name in agent_options}
        render.say(render.section("edit roles", "Enter keeps the current agent"))
        for role in roles.ROLES:
            current = roles.agent_for_role(role)
            chosen = prompt.choose(f"{role}  ({roles.capability_for(role)})",
                                   agent_options, current, descriptions=agent_desc)
            if chosen != current:
                config.write_setting(target, f"roles.{role}", chosen)
        render.say(f"{render.GREEN}saved{render.RESET}  {render.DIM}in {target}{render.RESET}")
        config.activate()  # refresh the in-memory mapping so the summary below is current
        render.say("")
        return _list()

    render.say("usage: guild roles <list|set|edit|reset> ...")
    return 1


def register(subparsers) -> None:
    parser = subparsers.add_parser("roles", help="see and change which agent plays each role")
    parser.add_argument("action", nargs="?", choices=["list", "set", "edit", "reset"],
                        default="list")
    parser.add_argument("role", nargs="?", help="role to set (with `set`)")
    parser.add_argument("agent", nargs="?", help="agent to assign (with `set`)")
    parser.add_argument("--global", dest="use_global", action="store_true",
                        help="target the global user config instead of the project")
    parser.set_defaults(func=cmd_roles, needs_project=False)

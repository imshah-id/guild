"""`guild completion <shell>`: print shell completion scripts."""
from __future__ import annotations

import argparse

from .. import render

_COMMANDS = (
    "init status run plan sessions report timeline label unlabel note resume retry skip monitor config research implement "
    "test review doctor scorecard completion"
)

_OPTIONS: dict[str, str] = {
    "init": "--analyze --preset --force",
    "run": "--gating --profile --plan-only --no-compact --model --effort --planner --researcher --implementer --reviewer --tester",
    "plan": "--drop --move --set --validate --run --no-compact",
    "sessions": "--limit -n --status --label --query -q planning running done failed blocked aborted",
    "report": "--output -o --open --json",
    "timeline": "--json latest",
    "label": "latest",
    "unlabel": "latest",
    "note": "latest",
    "resume": "--no-compact",
    "retry": "--run --no-compact",
    "skip": "--run --no-compact",
    "monitor": "--plain --json",
    "config": "--global list profiles get set unset",
    "doctor": "--live --project",
    "scorecard": "--json",
    "completion": "bash zsh fish",
}


def _bash() -> str:
    cases = "\n".join(
        f"    {name}) opts=\"{opts}\" ;;"
        for name, opts in sorted(_OPTIONS.items())
    )
    return f"""_guild_complete()
{{
  local cur cmd commands opts
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  cmd="${{COMP_WORDS[1]}}"
  commands="{_COMMANDS}"
  if [[ COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
    return 0
  fi
  case "$cmd" in
{cases}
    *) opts="" ;;
  esac
  COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}}
complete -F _guild_complete guild
"""


def _zsh() -> str:
    command_specs = " ".join(f"{name}:\"{opts}\"" for name, opts in sorted(_OPTIONS.items()))
    return f"""#compdef guild
_guild() {{
  local -a commands command_specs
  commands=({' '.join(_COMMANDS.split())})
  command_specs=({command_specs})
  if (( CURRENT == 2 )); then
    compadd "$@" -- "${{commands[@]}}"
    return
  fi
  local cmd="${{words[2]}}"
  local spec
  for spec in "${{command_specs[@]}}"; do
    if [[ "${{spec%%:*}}" == "$cmd" ]]; then
      compadd "$@" -- ${{=spec#*:}}
      return
    fi
  fi
}}
_guild "$@"
"""


def _fish() -> str:
    lines = ["complete -c guild -f"]
    for command in _COMMANDS.split():
        lines.append(f"complete -c guild -n '__fish_is_first_arg' -a {command}")
    for command, opts in sorted(_OPTIONS.items()):
        for option in opts.split():
            if option.startswith("--"):
                lines.append(f"complete -c guild -n '__fish_seen_subcommand_from {command}' -l {option[2:]}")
            elif option.startswith("-"):
                lines.append(f"complete -c guild -n '__fish_seen_subcommand_from {command}' -s {option[1:]}")
            else:
                lines.append(f"complete -c guild -n '__fish_seen_subcommand_from {command}' -a {option}")
    return "\n".join(lines) + "\n"


def cmd_completion(args: argparse.Namespace) -> int:
    scripts = {"bash": _bash, "zsh": _zsh, "fish": _fish}
    render.out(scripts[args.shell]().rstrip())
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("completion", help="print shell completion scripts")
    parser.add_argument("shell", choices=["bash", "zsh", "fish"])
    parser.set_defaults(func=cmd_completion, needs_project=False)

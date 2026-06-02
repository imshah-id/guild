"""`guild completion <shell>`: print shell completion scripts."""
from __future__ import annotations

import argparse

from .. import render

_COMMANDS = (
    "init status run plan sessions report resume retry skip monitor config research implement "
    "test review doctor scorecard completion"
)


def _bash() -> str:
    return f"""_guild_complete()
{{
  local cur prev commands
  COMPREPLY=()
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  commands="{_COMMANDS}"
  if [[ COMP_CWORD -eq 1 ]]; then
    COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
  fi
}}
complete -F _guild_complete guild
"""


def _zsh() -> str:
    return f"""#compdef guild
_guild() {{
  local -a commands
  commands=({' '.join(_COMMANDS.split())})
  if (( CURRENT == 2 )); then
    compadd "$@" -- "${{commands[@]}}"
  fi
}}
_guild "$@"
"""


def _fish() -> str:
    lines = ["complete -c guild -f"]
    for command in _COMMANDS.split():
        lines.append(f"complete -c guild -n '__fish_is_first_arg' -a {command}")
    return "\n".join(lines) + "\n"


def cmd_completion(args: argparse.Namespace) -> int:
    scripts = {"bash": _bash, "zsh": _zsh, "fish": _fish}
    render.out(scripts[args.shell]().rstrip())
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("completion", help="print shell completion scripts")
    parser.add_argument("shell", choices=["bash", "zsh", "fish"])
    parser.set_defaults(func=cmd_completion, needs_project=False)

"""Home interface shown by bare `guild`.

This is intentionally dependency-free: curses when attached to a real terminal, plain text when
stdout is redirected. It gives the CLI a proper landing surface instead of making users discover
everything from argparse help.
"""
from __future__ import annotations

import curses
import io
import shutil
import shlex
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from . import __version__, config, render, roles, scorecard, state

DEFAULT_WIDTH = 108


@dataclass(frozen=True)
class AgentRow:
    agent: str
    adapter: str
    assigned_roles: str
    model: str
    effort: str
    access: str
    status: str
    usage: str


@dataclass
class HomeState:
    command: str = ""
    transcript: list[str] | None = None
    message: str = "Type a guild command below. Example: status, sessions, report --open"

    def __post_init__(self) -> None:
        if self.transcript is None:
            self.transcript = []


_EMBEDDED_BLOCKED = {"run", "resume", "monitor", "research", "implement", "test", "review"}


def _clip(text: object, width: int) -> str:
    value = str(text)
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[:width - 3] + "..."


def _pad(text: object, width: int) -> str:
    return _clip(text, width).ljust(width)


def _agent_usage(data: dict, agent: str) -> str:
    item = (data.get("agents", {}) if isinstance(data, dict) else {}).get(agent, {})
    total = int(item.get("total", 0))
    ok = int(item.get("ok", 0))
    failed = int(item.get("failed", 0))
    avg = int(item.get("seconds", 0)) // total if total else 0
    if total == 0:
        return "no runs yet"
    return f"{ok}/{total} ok, {failed} fail, avg {avg}s"


def _latest_data() -> dict:
    latest = state.latest_session_dir()
    if latest is None:
        return {}
    return state.load_dict(latest / "state.json") or {"id": latest.name}


def _latest_summary() -> str:
    data = _latest_data()
    if not data:
        return "none"
    steps = data.get("steps", [])
    done = sum(1 for step in steps if step.get("status") in (state.DONE, state.SKIPPED))
    status = data.get("status", "unknown")
    return f"{data.get('id', '')}  {status}  {done}/{len(steps)} steps"


def agent_rows() -> list[AgentRow]:
    """Structured rows for the API/model/effort/usage section."""
    usage = scorecard.load()
    rows: list[AgentRow] = []
    for agent in roles.agent_names():
        try:
            spec = roles.spec_for_agent(agent)
            assigned: list[str] = []
            caps: set[str] = set()
            for role in roles.ROLES:
                try:
                    if roles.agent_for_role(role) == agent:
                        assigned.append(role)
                        caps.add(roles.capability_for(role))
                except roles.RoleError:
                    continue
            model = spec.model or "default"
            effort = spec.effort or "default"
            rows.append(AgentRow(
                agent=agent,
                adapter=spec.adapter,
                assigned_roles=", ".join(assigned) if assigned else "-",
                model=model,
                effort=effort,
                access="/".join(sorted(caps)) if caps else "-",
                status="available" if shutil.which(spec.bin) else "missing",
                usage=_agent_usage(usage, agent),
            ))
        except roles.RoleError as exc:
            rows.append(AgentRow(
                agent=agent,
                adapter="bad",
                assigned_roles="-",
                model="-",
                effort="-",
                access="-",
                status="error",
                usage=str(exc),
            ))
    return rows


def model_rows() -> list[str]:
    """Rows for tests and plain output compatibility."""
    return [
        f"  {row.agent:10} {row.adapter:9} {row.assigned_roles:28} {row.model:14} "
        f"{row.effort:8} {row.access:11} {row.status:9} {row.usage}"
        for row in agent_rows()
    ]


def _hr(width: int) -> str:
    return "+" + "-" * max(width - 2, 0) + "+"


def _box(title: str, body: list[str], width: int) -> list[str]:
    width = max(width, 48)
    label = f" {title} "
    top = "+" + label + "-" * max(width - len(label) - 2, 0) + "+"
    inner = width - 4
    lines = [top]
    for line in body:
        lines.append(f"| {_pad(line, inner)} |")
    lines.append(_hr(width))
    return lines


def _pair_line(left_label: str, left_value: object, right_label: str, right_value: object,
               width: int) -> str:
    half = max((width - 3) // 2, 20)
    left = f"{left_label}: {left_value}"
    right = f"{right_label}: {right_value}"
    return f"{_pad(left, half)} | {_pad(right, width - half - 3)}"


def _overview_body(width: int) -> list[str]:
    initialized = config.GUILD_DIR is not None
    project = str(config.PROJECT_ROOT) if initialized else "not initialized here"
    context = "ok" if (config.CONTEXT_PATH and config.CONTEXT_PATH.exists()) else "missing"
    context_value = f"{config.PROJECT_DIRNAME}/context.md {context}" if initialized else "run `guild init`"
    comp = config.setting("compaction", {}) or {}
    inner = width - 4
    return [
        _pair_line("Project", project, "Context", context_value, inner),
        _pair_line("Gating", config.setting("gating", config.DEFAULT_GATING),
                   "Compaction", "on" if comp.get("enabled") else "off", inner),
        _pair_line("Latest", _latest_summary(), "Config", "guild config list", inner),
    ]


def _api_body(width: int) -> list[str]:
    inner = width - 4
    fixed = 10 + 2 + 22 + 2 + 15 + 2 + 8 + 2 + 11 + 2 + 9 + 2
    usage_width = max(inner - fixed, 12)
    rows = [
        f"{_pad('API/CLI', 10)}  {_pad('Roles', 22)}  {_pad('Selected model', 15)}  "
        f"{_pad('Effort', 8)}  {_pad('Access', 11)}  {_pad('Status', 9)}  {_pad('Usage', usage_width)}",
        "-" * inner,
    ]
    for row in agent_rows():
        rows.append(
            f"{_pad(row.agent, 10)}  {_pad(row.assigned_roles, 22)}  {_pad(row.model, 15)}  "
            f"{_pad(row.effort, 8)}  {_pad(row.access, 11)}  {_pad(row.status, 9)}  {_pad(row.usage, usage_width)}"
        )
    return rows


def _latest_body(width: int) -> list[str]:
    data = _latest_data()
    if not data:
        return [
            "No sessions yet.",
            "Start one with: guild run \"<goal>\"",
        ]
    steps = data.get("steps", [])
    done = sum(1 for step in steps if step.get("status") in (state.DONE, state.SKIPPED))
    goal = str(data.get("goal", ""))
    return [
        f"Session: {data.get('id', '')}",
        f"Status:  {data.get('status', 'unknown')}    Progress: {render.progress(done, len(steps), width=14)}",
        f"Goal:    {goal}",
        "Open:    guild monitor    guild report --open",
    ]


def _actions_body() -> list[str]:
    return [
        "Type commands in the input bar, without the leading `guild`.",
        "status                  Show setup",
        "sessions                Browse previous runs",
        "report --open           Open latest Markdown report",
        "config profiles         Show model/effort presets",
        "doctor                  Check agent CLIs",
        "run \"<goal>\"            Runs outside the home UI for full interactivity",
    ]


def _transcript_body(ui: HomeState) -> list[str]:
    assert ui.transcript is not None
    if ui.transcript:
        return ui.transcript[-6:]
    return [ui.message]


def _input_body(ui: HomeState, width: int) -> list[str]:
    inner = width - 4
    prompt = "> "
    return [prompt + _clip(ui.command, max(inner - len(prompt), 1))]


def dashboard_lines(width: int = DEFAULT_WIDTH, ui: HomeState | None = None) -> list[str]:
    ui = ui or HomeState()
    width = max(width, 72)
    header_inner = width - 4
    title = f"guild {__version__}"
    subtitle = "agent team terminal"
    lines = [
        _hr(width),
        f"| {_pad(title, 18)} {_pad(subtitle, header_inner - 19)} |",
        _hr(width),
    ]
    lines.extend(_box("Overview", _overview_body(width), width))
    lines.extend(_box("API / CLI / selected models / effort / availability / usage", _api_body(width), width))
    lines.extend(_box("Latest Session", _latest_body(width), width))
    lines.extend(_box("Quick Actions", _actions_body(), width))
    lines.extend(_box("Command Output", _transcript_body(ui), width))
    lines.extend(_box("Command Input", _input_body(ui, width), width))
    lines.append("Keys: enter run, tab completes first word, backspace edit, q quit, r refresh")
    return lines


def home_lines() -> list[str]:
    return dashboard_lines(DEFAULT_WIDTH)


def open_home() -> None:
    if not sys.stdout.isatty():
        print("\n".join(home_lines()))
        return
    curses.wrapper(_loop)


def _loop(stdscr: "curses.window") -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(500)
    use_color = curses.has_colors()
    if use_color:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_CYAN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)

    ui = HomeState()

    while True:
        _draw(stdscr, use_color, ui)
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")) and not ui.command:
            break
        if ch in (ord("r"), ord("R"), -1) and not ui.command:
            continue
        if ch in (10, 13):
            _execute_typed(ui)
            continue
        if ch in (9,):
            _complete_command(ui)
            continue
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            ui.command = ui.command[:-1]
            continue
        if 32 <= ch <= 126:
            ui.command += chr(ch)
            continue


def _draw(stdscr: "curses.window", use_color: bool, ui: HomeState) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    w = max(width - 1, 72)
    lines = dashboard_lines(w, ui)
    for row, line in enumerate(lines[:max(height - 1, 0)]):
        attr = 0
        if row in (0, 1, 2) or line.startswith("+") and line.endswith("+"):
            attr = curses.A_BOLD
        if " missing " in line and use_color:
            attr |= curses.color_pair(4)
        elif " available " in line and use_color:
            attr |= curses.color_pair(1)
        stdscr.addnstr(row, 0, line, width - 1, attr)
    footer = f" q quit   r refresh   {time.strftime('%H:%M:%S')}"
    stdscr.addnstr(height - 1, 0, footer.ljust(width - 1), width - 1, curses.A_REVERSE)
    stdscr.refresh()


def _normalize_command(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text == "?":
        return ["help"]
    parts = shlex.split(text)
    if parts and parts[0] == "guild":
        parts = parts[1:]
    return parts


def _complete_command(ui: HomeState) -> None:
    from . import cli

    commands = sorted(_registered_commands(cli.build_parser()))
    current = ui.command.strip()
    if " " in current:
        return
    matches = [command for command in commands if command.startswith(current)]
    if len(matches) == 1:
        ui.command = matches[0] + " "
    elif matches:
        assert ui.transcript is not None
        ui.transcript = [f"completions: {', '.join(matches)}"]


def _registered_commands(parser) -> set[str]:
    commands: set[str] = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            commands.update(choices.keys())
    return commands


def _execute_typed(ui: HomeState) -> None:
    command = ui.command.strip()
    ui.command = ""
    lines, _ = run_embedded_command(command)
    ui.transcript = lines


def run_embedded_command(command: str) -> tuple[list[str], int]:
    parts = _normalize_command(command)
    if not parts:
        return ["No command entered."], 0
    if parts[0] in ("quit", "exit"):
        return ["Press q to quit the home interface."], 0
    if parts[0] == "help":
        return [
            "Try: status, sessions, report --open, config profiles, doctor",
            "Run interactive commands like `guild run \"<goal>\"` outside this home screen.",
        ], 0
    if parts[0] in _EMBEDDED_BLOCKED:
        return [
            f"`guild {parts[0]}` needs its own terminal flow.",
            f"Run it outside the home interface: guild {' '.join(parts)}",
        ], 1

    from . import cli

    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(parts)
    except SystemExit as exc:
        rc = int(exc.code or 0) if isinstance(exc.code, int) else 1
    except Exception as exc:  # Keep the home interface alive.
        return [f"error: {exc}"], 1

    text = (out.getvalue() + err.getvalue()).strip()
    lines = text.splitlines() if text else [f"guild {' '.join(parts)} finished with no output"]
    return lines[-8:], rc

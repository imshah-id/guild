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
MIN_WIDTH = 72


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
    message: str = "Type /help for slash commands, or run guild commands like status and sessions."
    quit_requested: bool = False

    def __post_init__(self) -> None:
        if self.transcript is None:
            self.transcript = []


_EMBEDDED_BLOCKED = {"run", "resume", "monitor", "research", "implement", "test", "review"}
_SLASH_COMMANDS: dict[str, list[str]] = {
    "/status": ["status"],
    "/sessions": ["sessions"],
    "/report": ["report"],
    "/profiles": ["config", "profiles"],
    "/config": ["config"],
    "/doctor": ["doctor"],
    "/scorecard": ["scorecard"],
    "/help": ["help"],
    "/clear": ["clear"],
    "/quit": ["quit"],
    "/exit": ["quit"],
}


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
    return "-" * max(width, 0)


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


def _border_top(width: int) -> str:
    return "+" + "-" * max(width - 2, 0) + "+"


def _border_bottom(width: int) -> str:
    return _border_top(width)


def _border_mid(left: str, right: str, width: int) -> str:
    label = f" {left} "
    right_label = f" {right} " if right else ""
    fill = max(width - len(label) - len(right_label) - 2, 0)
    return "+" + label + "-" * fill + right_label + "+"


def _panel_line(left: str, right: str, left_width: int, right_width: int) -> str:
    return f"| {_pad(left, left_width)} | {_pad(right, right_width)} |"


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
        "Slash commands work inside this interface.",
        "/status                 Show setup",
        "/sessions               Browse previous runs",
        "/report --open          Open latest Markdown report",
        "/profiles               Show model/effort presets",
        "/doctor                 Check agent CLIs",
        "/clear                  Clear command output",
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


def _project_name() -> str:
    if config.GUILD_DIR is None:
        return "not initialized"
    return str(config.PROJECT_ROOT)


def _model_summary() -> str:
    bits = []
    for row in agent_rows():
        bits.append(f"{row.agent}:{row.model}/{row.effort}")
    return "  ".join(bits) if bits else "no agents configured"


def _welcome_lines() -> list[str]:
    return [
        "Welcome to guild",
        "",
        "     ____  _   _ ___ _     ____",
        "    / ___|| | | |_ _| |   |  _ \\",
        "   | |  _ | | | || || |   | | | |",
        "   | |_| || |_| || || |___| |_| |",
        "    \\____| \\___/|___|_____|____/",
        "",
        f"Project  {_project_name()}",
        f"Gating   {config.setting('gating', config.DEFAULT_GATING)}",
    ]


def _tips_lines() -> list[str]:
    latest = _latest_summary()
    return [
        "Tips for getting started",
        "Run init to create project context.",
        "Run status for setup details.",
        "Run config profiles for presets.",
        "",
        "Current setup",
        f"Models  {_model_summary()}",
        f"Latest  {latest}",
    ]


def _hero_lines(width: int) -> list[str]:
    width = max(width, MIN_WIDTH)
    inner = width - 4
    gap = 3
    left_width = max(32, inner // 2 - gap)
    right_width = max(28, inner - left_width - gap)
    left = _welcome_lines()
    right = _tips_lines()
    rows = max(len(left), len(right))
    lines = [_border_top(width)]
    for index in range(rows):
        lines.append(_panel_line(
            left[index] if index < len(left) else "",
            right[index] if index < len(right) else "",
            left_width,
            right_width,
        ))
    lines.append(_border_bottom(width))
    return lines


def _notice_line(width: int) -> str:
    return _clip(
        "Type slash commands below - try /status, /sessions, /report --open, /profiles, /help",
        width,
    )


def _agents_lines(width: int) -> list[str]:
    width = max(width, MIN_WIDTH)
    inner = width - 4
    rows = [_border_mid("API / CLI agents", "selected models / effort / usage", width)]
    usage_width = max(inner - 81, 10)
    header = (
        f"{_pad('API', 10)} {_pad('Roles', 24)} {_pad('Model', 14)} {_pad('Effort', 8)} "
        f"{_pad('Access', 10)} {_pad('Status', 9)} {_pad('Usage', usage_width)}"
    )
    rows.append(f"| {_pad(header, inner)} |")
    rows.append(f"| {_hr(inner)} |")
    for row in agent_rows():
        line = (
            f"{_pad(row.agent, 10)} {_pad(row.assigned_roles, 24)} {_pad(row.model, 14)} "
            f"{_pad(row.effort, 8)} {_pad(row.access, 10)} {_pad(row.status, 9)} "
            f"{_pad(row.usage, usage_width)}"
        )
        rows.append(f"| {_pad(line, inner)} |")
    rows.append(_border_bottom(width))
    return rows


def _transcript_lines(ui: HomeState, width: int) -> list[str]:
    width = max(width, MIN_WIDTH)
    body = _transcript_body(ui)[-4:]
    return [
        _border_mid("Output", "", width),
        *[f"| {_pad(line, width - 4)} |" for line in body],
        _border_bottom(width),
    ]


def _prompt_lines(ui: HomeState, width: int) -> list[str]:
    width = max(width, MIN_WIDTH)
    prompt = "> " + ui.command
    return [
        _hr(width),
        _clip(prompt, width),
        _hr(width),
        "/help commands  |  Enter run  |  Tab complete  |  q quit",
    ]


def dashboard_lines(width: int = DEFAULT_WIDTH, ui: HomeState | None = None) -> list[str]:
    ui = ui or HomeState()
    width = max(width, MIN_WIDTH)
    lines = [
        f"{_pad('guild ' + __version__, 22)} agent team terminal",
        _hr(width),
    ]
    lines.extend(_hero_lines(width))
    lines.append("")
    lines.append(_notice_line(width))
    lines.append("")
    lines.extend(_agents_lines(width))
    lines.append("")
    lines.extend(_transcript_lines(ui, width))
    lines.extend(_prompt_lines(ui, width))
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
        curses.init_pair(5, curses.COLOR_MAGENTA, -1)
        curses.init_pair(6, curses.COLOR_BLUE, -1)
        curses.init_pair(7, curses.COLOR_WHITE, -1)

    ui = HomeState()

    while True:
        _draw(stdscr, use_color, ui)
        if ui.quit_requested:
            break
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
        attr = _line_attr(line, row, use_color)
        stdscr.addnstr(row, 0, line, width - 1, attr)
    footer = f" q quit   r refresh   {time.strftime('%H:%M:%S')}"
    stdscr.addnstr(height - 1, 0, footer.ljust(width - 1), width - 1, curses.A_REVERSE)
    stdscr.refresh()


def _line_attr(line: str, row: int, use_color: bool) -> int:
    attr = 0
    if row == 0:
        attr |= curses.A_BOLD
        return attr | (curses.color_pair(2) if use_color else 0)
    if line.startswith("? shortcuts") or line.startswith("/help"):
        return curses.A_DIM
    if line.startswith(">"):
        attr |= curses.A_BOLD
        return attr | (curses.color_pair(2) if use_color else 0)
    if line.startswith("-"):
        return curses.A_DIM
    if line.startswith("+"):
        attr |= curses.A_BOLD
        if not use_color:
            return attr
        if "Output" in line:
            return attr | curses.color_pair(3)
        if "API / CLI" in line:
            return attr | curses.color_pair(5)
        return attr | curses.color_pair(2)
    if " missing " in line or " error" in line or line.startswith("Unknown slash"):
        return attr | (curses.color_pair(4) if use_color else 0)
    if " available " in line:
        return attr | (curses.color_pair(1) if use_color else 0)
    if "Welcome to guild" in line or "Tips for getting started" in line:
        attr |= curses.A_BOLD
        return attr | (curses.color_pair(3) if use_color else 0)
    if line.strip().startswith("/"):
        return attr | (curses.color_pair(2) if use_color else 0)
    return attr


def _normalize_command(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text == "?":
        return ["help"]
    parts = shlex.split(text)
    if parts and parts[0].startswith("/"):
        mapped = _SLASH_COMMANDS.get(parts[0])
        if mapped is None:
            return ["unknown-slash", parts[0], *parts[1:]]
        return [*mapped, *parts[1:]]
    if parts and parts[0] == "guild":
        parts = parts[1:]
    return parts


def _complete_command(ui: HomeState) -> None:
    from . import cli

    commands = sorted([*_registered_commands(cli.build_parser()), *_SLASH_COMMANDS])
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
    parts = _normalize_command(command)
    if parts and parts[0] == "quit":
        ui.quit_requested = True
        return
    if parts and parts[0] == "clear":
        ui.transcript = []
        ui.message = "Output cleared."
        return
    lines, _ = run_embedded_command(command)
    ui.transcript = lines


def run_embedded_command(command: str) -> tuple[list[str], int]:
    parts = _normalize_command(command)
    if not parts:
        return ["No command entered."], 0
    if parts[0] == "unknown-slash":
        return [f"Unknown slash command: {parts[1]}", "Type /help to see available commands."], 1
    if parts[0] == "clear":
        return [], 0
    if parts[0] in ("quit", "exit"):
        return ["Press q to quit the home interface."], 0
    if parts[0] == "help":
        return [
            "Slash commands: /status, /sessions, /report --open, /profiles, /doctor, /scorecard, /clear, /quit",
            "You can also type normal guild commands without the leading `guild`.",
            "Interactive flows like run/resume/monitor should be launched outside this screen.",
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

"""Home interface shown by bare `guild`.

This is intentionally dependency-free: curses when attached to a real terminal, plain text when
stdout is redirected. It gives the CLI a proper landing surface instead of making users discover
everything from argparse help.
"""
from __future__ import annotations

import curses
import io
import locale
import shutil
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from . import __version__, config, roles, scorecard, state

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
    "/timeline": ["timeline"],
    "/agents": ["agents-view"],
    "/profiles": ["config", "profiles"],
    "/config": ["config"],
    "/doctor": ["doctor"],
    "/scorecard": ["scorecard"],
    "/help": ["help"],
    "/clear": ["clear"],
    "/quit": ["quit"],
    "/quite": ["quit"],
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


def _agent_item(data: dict, agent: str) -> dict:
    agents = data.get("agents", {}) if isinstance(data, dict) else {}
    item = agents.get(agent, {}) if isinstance(agents, dict) else {}
    return item if isinstance(item, dict) else {}


def _phase_summary(item: dict) -> str:
    phases = item.get("phases", {})
    if not isinstance(phases, dict) or not phases:
        return "phases none"
    bits: list[str] = []
    for phase in sorted(phases):
        data = phases.get(phase, {})
        if not isinstance(data, dict):
            continue
        total = int(data.get("total", 0))
        ok = int(data.get("ok", 0))
        bits.append(f"{phase}:{ok}/{total}")
    return "phases " + (", ".join(bits) if bits else "none")


def _verdict_summary(item: dict) -> str:
    verdicts = item.get("verdicts", {})
    if not isinstance(verdicts, dict) or not verdicts:
        return "verdicts none"
    bits = [f"{name}={count}" for name, count in sorted(verdicts.items())]
    return "verdicts " + ", ".join(bits)


def agent_detail_lines() -> list[str]:
    usage = scorecard.load()
    lines = ["Agent details"]
    for row in agent_rows():
        item = _agent_item(usage, row.agent)
        total = int(item.get("total", 0))
        ok = int(item.get("ok", 0))
        failed = int(item.get("failed", 0))
        avg = int(item.get("seconds", 0)) // total if total else 0
        model = f"model {row.model}"
        effort = f"effort {row.effort}"
        lines.append(
            f"{row.agent}: {row.assigned_roles} | {model} | {effort} | "
            f"{row.access} | {row.status} | {ok}/{total} ok, {failed} fail, avg {avg}s"
        )
        detail = " | ".join(part for part in (_phase_summary(item), _verdict_summary(item)) if part)
        lines.append(f"  {detail}")
    return lines


def help_lines() -> list[str]:
    return [
        "Slash commands",
        "/status      show resolved setup",
        "/sessions    browse previous runs",
        "/timeline    show latest run events",
        "/agents      inspect agent usage detail",
        "/report      print latest Markdown report",
        "/profiles    list model and effort presets",
        "/doctor      check agent CLIs and config",
        "/scorecard   show per-agent outcomes",
        "/clear       clear command output",
        "/quit        exit the home interface",
        "/quite       exit the home interface",
    ]


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


# --- box drawing ----------------------------------------------------------------------------
# Every emitted line is exactly `width` columns and carries its own left/right wall, so the right
# edge is always a single straight vertical line. (The previous layout mixed full-width title
# bars with walled rows, which made the right edge zig-zag and the columns drift.)

_TL, _TR, _BL, _BR = "╭", "╮", "╰", "╯"   # ╭ ╮ ╰ ╯
_HZ, _VT = "─", "│"                                 # ─ │
_ML, _MR = "├", "┤"                                 # ├ ┤
_DOT = "·"                                               # ·


def _box_top(title: str, width: int) -> str:
    label = f" {title} " if title else ""
    return _TL + label + _HZ * max(width - 2 - len(label), 0) + _TR


def _box_bottom(width: int) -> str:
    return _BL + _HZ * max(width - 2, 0) + _BR


def _box_div(width: int) -> str:
    return _ML + _HZ * max(width - 2, 0) + _MR


def _row(content: object, width: int) -> str:
    inner = max(width - 4, 0)
    return f"{_VT} {_pad(content, inner)} {_VT}"


def _columns(left: list[str], right: list[str], width: int) -> list[str]:
    """Two side-by-side columns sharing one box's inner width, each its own padded sub-field."""
    inner = max(width - 4, 0)
    gap = 3
    left_w = max((inner - gap) // 2, 1)
    right_w = max(inner - gap - left_w, 1)
    height = max(len(left), len(right))
    rows: list[str] = []
    for index in range(height):
        cell_l = left[index] if index < len(left) else ""
        cell_r = right[index] if index < len(right) else ""
        rows.append(_row(f"{_pad(cell_l, left_w)}{' ' * gap}{_pad(cell_r, right_w)}", width))
    return rows


# --- sections -------------------------------------------------------------------------------

def _identity_lines() -> list[str]:
    project = str(config.PROJECT_ROOT) if config.GUILD_DIR is not None else "not initialized"
    return [
        f"Project   {project}",
        f"Gating    {config.setting('gating', config.DEFAULT_GATING)}",
        f"Version   {__version__}",
        f"Latest    {_latest_summary()}",
    ]


def _quicklinks_lines() -> list[str]:
    return [
        "Getting started",
        "/status     inspect the resolved setup",
        "/sessions   browse previous runs",
        "/timeline   show the latest run events",
        "/agents     inspect agent usage detail",
        "/profiles   model & effort presets",
        "/report     open the latest summary",
        "/help       all slash commands",
    ]


def _overview_section(width: int) -> list[str]:
    return [
        _box_top("Overview", width),
        *_columns(_identity_lines(), _quicklinks_lines(), width),
        _box_bottom(width),
    ]


def _agents_section(width: int) -> list[str]:
    inner = max(width - 4, 0)
    agent_w, roles_w, model_w, effort_w, access_w, status_w = 8, 20, 13, 7, 10, 10
    fixed = agent_w + roles_w + model_w + effort_w + access_w + status_w + 6  # 6 separators
    usage_w = max(inner - fixed, 6)

    def cells(c1, c2, c3, c4, c5, c6, c7) -> str:
        return (f"{_pad(c1, agent_w)} {_pad(c2, roles_w)} {_pad(c3, model_w)} {_pad(c4, effort_w)} "
                f"{_pad(c5, access_w)} {_pad(c6, status_w)} {_pad(c7, usage_w)}")

    lines = [
        _box_top("API / CLI agents  " + _DOT + "  selected models / effort / usage", width),
        _row(cells("API", "Roles", "Model", "Effort", "Access", "Status", "Usage"), width),
        _box_div(width),
    ]
    for row in agent_rows():
        lines.append(_row(
            cells(row.agent, row.assigned_roles, row.model, row.effort,
                  row.access, row.status, row.usage),
            width,
        ))
    lines.append(_box_bottom(width))
    return lines


def _transcript_body(ui: HomeState) -> list[str]:
    assert ui.transcript is not None
    if ui.transcript:
        return ui.transcript[-12:]
    return [ui.message]


def _output_section(ui: HomeState, width: int) -> list[str]:
    return [
        _box_top("Command output", width),
        *[_row(line, width) for line in _transcript_body(ui)],
        _box_bottom(width),
    ]


def _input_section(ui: HomeState, width: int) -> list[str]:
    return [
        _box_top("Command input", width),
        _row("> " + ui.command, width),
        _box_bottom(width),
        f"  /help commands   {_DOT}   enter run   {_DOT}   tab complete   {_DOT}   /quit exit",
    ]


def dashboard_lines(width: int = DEFAULT_WIDTH, ui: HomeState | None = None) -> list[str]:
    ui = ui or HomeState()
    width = max(width, MIN_WIDTH)
    return [
        *_overview_section(width),
        "",
        *_agents_section(width),
        "",
        *_output_section(ui, width),
        "",
        *_input_section(ui, width),
    ]


def home_lines() -> list[str]:
    return dashboard_lines(DEFAULT_WIDTH)


def open_home() -> None:
    if not sys.stdout.isatty():
        print("\n".join(home_lines()))
        return
    # curses needs a UTF-8 locale to render the box-drawing characters; without this the
    # borders show up as garbage on some terminals.
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
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
        if _handle_key(ui, ch):
            break


def _handle_key(ui: HomeState, ch: int) -> bool:
    if ch in (ord("r"), ord("R"), -1) and not ui.command:
        return False
    if ch in (10, 13):
        _execute_typed(ui)
        return ui.quit_requested
    if ch in (9,):
        _complete_command(ui)
        return False
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        ui.command = ui.command[:-1]
        return False
    if 32 <= ch <= 126:
        ui.command += chr(ch)
    return ui.quit_requested


def _draw(stdscr: "curses.window", use_color: bool, ui: HomeState) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    w = max(width - 1, 72)
    lines = dashboard_lines(w, ui)
    for row, line in enumerate(lines[:max(height - 1, 0)]):
        attr = _line_attr(line, row, use_color)
        stdscr.addnstr(row, 0, line, width - 1, attr)
    stdscr.refresh()


def _pair(index: int, use_color: bool) -> int:
    return curses.color_pair(index) if use_color else 0


def _line_attr(line: str, row: int, use_color: bool) -> int:
    if not line:
        return 0
    head = line[0]

    # Box top border: bold title tinted by section.
    if head == _TL:
        accent = 2
        if "API / CLI" in line:
            accent = 5
        elif "Command output" in line:
            accent = 3
        elif "Command input" in line:
            accent = 2
        elif "Overview" in line:
            accent = 6
        return curses.A_BOLD | _pair(accent, use_color)

    # Bottom border and inner divider: quiet rails.
    if head in (_BL, _ML):
        return curses.A_DIM

    # Content rows: tint by what the row carries.
    if head == _VT:
        body = line[1:].strip()
        if " missing " in line or " error" in line.lower() or "Unknown slash" in line:
            return _pair(4, use_color)
        if " available " in line:
            return _pair(1, use_color)
        if body.startswith(">"):
            return curses.A_BOLD | _pair(2, use_color)
        if body.startswith("/"):
            return _pair(2, use_color)
        return 0

    # Footer hint line beneath the input box.
    if line.lstrip().startswith("/help"):
        return curses.A_DIM
    return 0


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
        return ["Use /quit to exit the home interface."], 0
    if parts[0] == "help":
        return help_lines(), 0
    if parts[0] == "agents-view":
        return agent_detail_lines(), 0
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

"""Home interface shown by bare `guild`.

This is intentionally dependency-free: curses when attached to a real terminal, plain text when
stdout is redirected. It gives the CLI a proper landing surface instead of making users discover
everything from argparse help.
"""
from __future__ import annotations

import curses
import shutil
import sys
import time

from . import config, render, roles, scorecard, state


def _agent_usage(data: dict, agent: str) -> str:
    item = (data.get("agents", {}) if isinstance(data, dict) else {}).get(agent, {})
    total = int(item.get("total", 0))
    ok = int(item.get("ok", 0))
    failed = int(item.get("failed", 0))
    avg = int(item.get("seconds", 0)) // total if total else 0
    if total == 0:
        return "no runs yet"
    return f"{ok}/{total} ok, {failed} fail, avg {avg}s"


def _latest_summary() -> str:
    latest = state.latest_session_dir()
    if latest is None:
        return "none"
    data = state.load_dict(latest / "state.json") or {}
    steps = data.get("steps", [])
    done = sum(1 for step in steps if step.get("status") in (state.DONE, state.SKIPPED))
    status = data.get("status", "unknown")
    return f"{data.get('id', latest.name)}  {status}  {done}/{len(steps)} steps"


def model_rows() -> list[str]:
    """Rows for the API/model/effort/usage section."""
    usage = scorecard.load()
    rows: list[str] = []
    for role in roles.ROLES:
        try:
            agent = roles.agent_for_role(role)
            spec = roles.spec_for_agent(agent)
            cap = roles.capability_for(role)
            available = "available" if shutil.which(spec.bin) else "missing"
            model = spec.model or "default"
            effort = spec.effort or "default"
            rows.append(
                f"  {role:12} {agent:10} {spec.adapter:9} {model:14} "
                f"{effort:8} {cap:10} {available:9} {_agent_usage(usage, agent)}"
            )
        except roles.RoleError as exc:
            rows.append(f"  {role:12} {render.RED}{exc}{render.RESET}")
    return rows


def home_lines() -> list[str]:
    project = str(config.PROJECT_ROOT) if config.GUILD_DIR is not None else "not initialized here"
    context = "ok" if (config.CONTEXT_PATH and config.CONTEXT_PATH.exists()) else "missing"
    comp = config.setting("compaction", {}) or {}
    lines = [
        render.banner("guild", ("interface", "home"), ("version", "local")),
        render.kv("project", project),
        render.kv("context", f"{config.PROJECT_DIRNAME}/context.md {context}" if config.GUILD_DIR else "run `guild init`"),
        render.kv("gating", config.setting("gating", config.DEFAULT_GATING)),
        render.kv("compaction", "on" if comp.get("enabled") else "off"),
        render.kv("latest", _latest_summary()),
        "",
        render.section("API / CLI, selected models, effort, usage"),
        "  role         agent      api/cli   model          effort   access     status    usage",
        *model_rows(),
        "",
        render.section("commands"),
        "  run <goal>        plan, build, cross-review, test",
        "  monitor           live dashboard for latest session",
        "  sessions          previous runs",
        "  report --open     write and open latest report",
        "  config profiles   available model/effort profiles",
        "  doctor --live     check configured agent CLIs",
        "",
        render.kv("keys", "q quit, r refresh"),
    ]
    return lines


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

    while True:
        _draw(stdscr, use_color)
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q")):
            break
        if ch in (ord("r"), ord("R"), -1):
            continue


def _draw(stdscr: "curses.window", use_color: bool) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    w = max(width - 1, 20)

    title_attr = curses.A_BOLD | (curses.color_pair(2) if use_color else 0)
    stdscr.addnstr(0, 0, " guild ", w, title_attr)
    stdscr.addnstr(0, 8, "agent team interface", max(w - 8, 1), curses.A_DIM)
    stdscr.addnstr(1, 0, f" project: {config.PROJECT_ROOT if config.GUILD_DIR else 'not initialized here'}", w)
    stdscr.addnstr(
        2, 0,
        f" gating: {config.setting('gating', config.DEFAULT_GATING)}   latest: {_latest_summary()}",
        w,
        curses.A_DIM,
    )

    row = 4
    stdscr.addnstr(row, 0, " API / CLI, selected models, effort, usage ", w, curses.A_BOLD)
    row += 1
    stdscr.addnstr(row, 0, " role         agent      api/cli   model          effort   access     status    usage", w, curses.A_DIM)
    row += 1
    for line in model_rows():
        if row >= height - 8:
            break
        attr = 0
        if " missing " in line and use_color:
            attr = curses.color_pair(4)
        elif " available " in line and use_color:
            attr = curses.color_pair(1)
        stdscr.addnstr(row, 0, line, w, attr)
        row += 1

    row += 1
    if row < height - 2:
        stdscr.addnstr(row, 0, " Commands ", w, curses.A_BOLD)
        commands = [
            "run <goal>      plan/build/review/test",
            "monitor         live session dashboard",
            "sessions        previous runs",
            "report --open   open latest Markdown report",
            "config profiles model/effort presets",
        ]
        for command in commands:
            row += 1
            if row >= height - 2:
                break
            stdscr.addnstr(row, 0, " " + command, w)

    footer = f" q quit   r refresh   {time.strftime('%H:%M:%S')}"
    stdscr.addnstr(height - 1, 0, footer.ljust(w), w, curses.A_REVERSE)
    stdscr.refresh()

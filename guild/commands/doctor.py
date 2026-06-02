"""`guild doctor`: check that the configured agent CLIs are installed, and validate config."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass

from .. import config, render, roles


@dataclass(frozen=True)
class ProjectCheck:
    level: str
    item: str
    detail: str


def _ping(cmd: list[str], *, last_line: bool = False) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                             cwd=str(config.PROJECT_ROOT))
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"(error: {exc})"
    text = out.stdout.strip()
    if last_line and text:
        text = text.splitlines()[-1]
    return text[:40] if text else "(no output)"


def _check_mark(level: str) -> str:
    if level == "ok":
        return f"{render.GREEN}ok  {render.RESET}"
    if level == "warn":
        return f"{render.YELLOW}warn{render.RESET}"
    return f"{render.RED}MISS{render.RESET}"


def project_checks() -> list[ProjectCheck]:
    checks: list[ProjectCheck] = []
    if config.GUILD_DIR is None:
        return [ProjectCheck("miss", "project", "not initialized here; run `guild init`")]

    guild_dir = config.GUILD_DIR
    checks.append(ProjectCheck("ok", ".guild", str(guild_dir)))

    config_path = guild_dir / "config.json"
    if not config_path.exists():
        checks.append(ProjectCheck("miss", "config", ".guild/config.json is missing"))
    else:
        try:
            parsed = json.loads(config_path.read_text())
            checks.append(ProjectCheck(
                "ok" if isinstance(parsed, dict) else "miss",
                "config",
                ".guild/config.json is readable JSON" if isinstance(parsed, dict) else "top-level JSON must be an object",
            ))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(ProjectCheck("miss", "config", f".guild/config.json is not readable JSON: {exc}"))

    context_path = guild_dir / "context.md"
    if not context_path.exists():
        checks.append(ProjectCheck("miss", "context", ".guild/context.md is missing"))
    else:
        try:
            text = context_path.read_text().strip()
        except OSError as exc:
            checks.append(ProjectCheck("miss", "context", f".guild/context.md is not readable: {exc}"))
        else:
            if not text:
                checks.append(ProjectCheck("miss", "context", ".guild/context.md is empty"))
            elif "<" in text and ">" in text:
                checks.append(ProjectCheck("warn", "context", "context.md still appears to contain template placeholders"))
            else:
                checks.append(ProjectCheck("ok", "context", ".guild/context.md has project instructions"))

    runs_dir = guild_dir / "runs"
    if not runs_dir.is_dir():
        checks.append(ProjectCheck("miss", "runs", ".guild/runs is missing"))
    else:
        checks.append(ProjectCheck("ok", "runs", ".guild/runs exists"))
        runs_ignore = runs_dir / ".gitignore"
        if not runs_ignore.exists():
            checks.append(ProjectCheck("warn", "runs gitignore", ".guild/runs/.gitignore is missing"))
        else:
            try:
                ignored = "*" in runs_ignore.read_text().splitlines()
            except OSError:
                ignored = False
            checks.append(ProjectCheck(
                "ok" if ignored else "warn",
                "runs gitignore",
                "run logs are gitignored" if ignored else ".guild/runs/.gitignore should ignore run logs",
            ))

    session_dirs = []
    if config.RUNS_DIR.exists():
        session_dirs = [path for path in config.RUNS_DIR.iterdir() if path.is_dir()]
    if session_dirs:
        newest = max(session_dirs, key=lambda path: path.stat().st_mtime)
        latest = newest / "state.json"
        readable = state_path_readable(latest)
        checks.append(ProjectCheck(
            "ok" if readable else "miss",
            "latest state",
            f"{latest.relative_to(config.PROJECT_ROOT)} is readable"
            if readable
            else f"{latest.relative_to(config.PROJECT_ROOT)} is missing or invalid",
        ))
    return checks


def state_path_readable(path) -> bool:
    from .. import state

    return path.exists() and state.load_dict(path) is not None


def project_check_lines(checks: list[ProjectCheck] | None = None) -> list[str]:
    checks = checks if checks is not None else project_checks()
    return [f"  {_check_mark(check.level)} {check.item:14} {check.detail}" for check in checks]


def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    render.out(f"{render.BOLD}agents{render.RESET}")
    present: dict[str, str] = {}
    for name in roles.agent_names():
        try:
            spec = roles.spec_for_agent(name)
        except roles.RoleError as exc:
            render.out(f"  {render.RED}bad {render.RESET} {name}: {exc}")
            ok = False
            continue
        if shutil.which(spec.bin):
            present[name] = spec.bin
            render.out(f"  {render.GREEN}ok  {render.RESET} {name:8} {spec.adapter} adapter ({spec.bin})")
        else:
            render.out(f"  {render.RED}MISS{render.RESET} {name:8} {spec.bin} not on PATH")
            ok = False

    render.out("")
    render.out(f"{render.BOLD}routing{render.RESET} "
               f"{render.DIM}(role -> agent that will actually run){render.RESET}")
    for role in roles.ROLES:
        try:
            assignment = roles.resolve_role(role)
        except roles.RoleError as exc:
            render.out(f"  {render.RED}MISS{render.RESET} {role:12} {exc}")
            ok = False
            continue
        resolved = assignment.spec.name
        if not roles.installed(resolved):
            render.out(f"  {render.RED}MISS{render.RESET} {role:12} {resolved} not on PATH")
            ok = False
        elif assignment.fallback_from:
            render.out(f"  {render.YELLOW}sub {render.RESET} {role:12} "
                       f"{assignment.fallback_from} -> {resolved}  {render.DIM}({assignment.reason}){render.RESET}")
        else:
            render.out(f"  {render.GREEN}ok  {render.RESET} {role:12} {resolved}")

    render.out("")
    render.out(f"{render.BOLD}config{render.RESET}")
    conflict = roles.cross_review_conflict()
    if conflict:
        render.out(f"  {render.YELLOW}warn{render.RESET} reviewer == implementer ('{conflict}'); "
                   "cross-review will substitute a different agent")
    else:
        render.out(f"  {render.GREEN}ok  {render.RESET} cross-review: reviewer differs from implementer")

    if args.project:
        render.out("")
        render.out(f"{render.BOLD}project{render.RESET}")
        checks = project_checks()
        for line in project_check_lines(checks):
            render.out(line)
        if any(check.level == "miss" for check in checks):
            ok = False

    if args.live and present:
        render.out("")
        render.out(f"{render.BOLD}live ping{render.RESET} {render.DIM}(one tiny prompt each, costs a call){render.RESET}")
        for name, binary in present.items():
            adapter = roles.spec_for_agent(name).adapter
            if adapter == "claude":
                render.out(f"  {name}: {_ping([binary, '-p', 'reply with the single word ok'])}")
            elif adapter == "codex":
                render.out(f"  {name}: {_ping([binary, 'exec', '-s', 'read-only', '--skip-git-repo-check', 'reply with the single word ok'], last_line=True)}")
            elif adapter == "agy":
                render.out(f"  {name}: {_ping([binary, '--print', '--print-timeout', '60s', 'reply with the single word ok'])}")
    return 0 if ok else 1


def register(subparsers) -> None:
    parser = subparsers.add_parser("doctor", help="check the configured agent CLIs and config")
    parser.add_argument("--live", action="store_true", help="also ping each agent (costs a call)")
    parser.add_argument("--project", action="store_true", help="also check .guild project files")
    parser.set_defaults(func=cmd_doctor, needs_project=False)

"""Read-only git helpers for reporting workspace changes."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import config


def _git(args: list[str], root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def is_git(root: Path | None = None) -> bool:
    return _git(["rev-parse", "--is-inside-work-tree"], root or config.PROJECT_ROOT) == "true"


def workspace_diff(root: Path | None = None) -> tuple[list[str], str]:
    """Return changed files from status and a tracked-file diff stat for the worktree."""
    root = root or config.PROJECT_ROOT
    if not is_git(root):
        return [], ""
    status = _git(["status", "--short"], root)
    files: list[str] = []
    for line in status.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    diff_stat = _git(["diff", "--stat", "HEAD", "--"], root)
    return sorted(dict.fromkeys(files)), diff_stat

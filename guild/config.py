"""Layered configuration and project discovery.

Resolution order, lowest to highest precedence:

    built-in DEFAULTS  <  ~/.config/guild/config.json (global)  <  <project>/.guild/config.json

CLI flags are layered on top at runtime by `apply_overrides`. Config files are JSON so the
standard library can both read and write them with zero dependencies (stdlib `tomllib` cannot
write TOML, and pulling in a TOML writer would add a dependency for no real gain). `guild config`
edits these files for you, so hand-editing is optional.

A handful of module-level globals (PROJECT_ROOT, GUILD_DIR, RUNS_DIR, CONTEXT_PATH, plus the
limit/compaction convenience constants) are set by `activate()` once the project is discovered.
The rest of the package reads those globals rather than threading a config object everywhere.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

PROJECT_DIRNAME = ".guild"

GATING_MODES = ("guided", "hands-off", "checkpoint")

# Built-in defaults. A project's config.json overrides any subset of this; anything it omits
# falls back to here, so new keys stay correct as the tool grows.
DEFAULTS: dict = {
    "agents": {
        "claude": {"bin": "claude", "adapter": "claude", "model": None, "effort": None},
        "codex": {"bin": "codex", "adapter": "codex", "model": None, "effort": None,
                  "sandbox": "workspace-write"},
        "agy": {"bin": "agy", "adapter": "agy", "model": None},
    },
    "roles": {
        "planner": "claude",
        "researcher": "agy",
        "implementer": "codex",
        "reviewer": "claude",
        "tester": "codex",
    },
    "gating": "guided",
    "compaction": {
        "enabled": True,
        "summary_chars": 1500,
        "report_chars": 2000,
        "review_chars": 2000,
        "research_chars": 280,
    },
    "limits": {
        "max_fix_attempts": 3,
        "step_timeout": 1800,
        "planner_timeout": 600,
        "research_timeout": 600,
    },
}


def global_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "guild"


def global_config_path() -> Path:
    return global_dir() / "config.json"


# --- discovery ---------------------------------------------------------------------------

def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (default CWD) looking for a `.guild/` directory, like git."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / PROJECT_DIRNAME).is_dir():
            return directory
    return None


# --- merge -------------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict, override: dict, source: str, sources: dict, prefix: str = "") -> dict:
    """Merge `override` onto `base` (recursively for nested dicts), recording for each leaf
    which `source` last set it (used by `guild config list`)."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value, source, sources, prefix=f"{dotted}.")
        else:
            out[key] = copy.deepcopy(value)
            sources[dotted] = source
    return out


def resolve(project_root: Path | None) -> tuple[dict, dict]:
    """Build the merged settings dict and a {dotted_key: source} map."""
    sources: dict = {}
    settings = _deep_merge(DEFAULTS, {}, "default", sources)

    def mark_defaults(node: dict, prefix: str = "") -> None:
        for key, value in node.items():
            dotted = f"{prefix}{key}"
            if isinstance(value, dict):
                mark_defaults(value, f"{dotted}.")
            else:
                sources.setdefault(dotted, "default")

    mark_defaults(DEFAULTS)

    global_data = _read_json(global_config_path())
    if global_data:
        settings = _deep_merge(settings, global_data, "global", sources)
    if project_root is not None:
        project_data = _read_json(project_root / PROJECT_DIRNAME / "config.json")
        if project_data:
            settings = _deep_merge(settings, project_data, "project", sources)
    return settings, sources


# --- activated globals -------------------------------------------------------------------

PROJECT_ROOT: Path = Path.cwd()
GUILD_DIR: Path | None = None
RUNS_DIR: Path = Path.cwd() / PROJECT_DIRNAME / "runs"
CONTEXT_PATH: Path | None = None
PROJECT_ROLES_DIR: Path | None = None
SETTINGS: dict = copy.deepcopy(DEFAULTS)
SOURCES: dict = {}

# Convenience constants derived from SETTINGS (kept flat so the engine can read them directly).
MAX_FIX_ATTEMPTS = DEFAULTS["limits"]["max_fix_attempts"]
STEP_TIMEOUT_SECONDS = DEFAULTS["limits"]["step_timeout"]
PLANNER_TIMEOUT_SECONDS = DEFAULTS["limits"]["planner_timeout"]
RESEARCH_TIMEOUT_SECONDS = DEFAULTS["limits"]["research_timeout"]
COMPACTION_ENABLED = DEFAULTS["compaction"]["enabled"]
COMPACT_SUMMARY_CHARS = DEFAULTS["compaction"]["summary_chars"]
COMPACT_REPORT_CHARS = DEFAULTS["compaction"]["report_chars"]
COMPACT_REVIEW_CHARS = DEFAULTS["compaction"]["review_chars"]
RESEARCH_NOTE_CHARS = DEFAULTS["compaction"]["research_chars"]
DEFAULT_GATING = DEFAULTS["gating"]


def _refresh_constants() -> None:
    """Re-derive the flat convenience constants from the current SETTINGS."""
    global MAX_FIX_ATTEMPTS, STEP_TIMEOUT_SECONDS, PLANNER_TIMEOUT_SECONDS, RESEARCH_TIMEOUT_SECONDS
    global COMPACTION_ENABLED, COMPACT_SUMMARY_CHARS, COMPACT_REPORT_CHARS, COMPACT_REVIEW_CHARS
    global RESEARCH_NOTE_CHARS, DEFAULT_GATING
    limits = SETTINGS.get("limits", {})
    comp = SETTINGS.get("compaction", {})
    MAX_FIX_ATTEMPTS = limits.get("max_fix_attempts", MAX_FIX_ATTEMPTS)
    STEP_TIMEOUT_SECONDS = limits.get("step_timeout", STEP_TIMEOUT_SECONDS)
    PLANNER_TIMEOUT_SECONDS = limits.get("planner_timeout", PLANNER_TIMEOUT_SECONDS)
    RESEARCH_TIMEOUT_SECONDS = limits.get("research_timeout", RESEARCH_TIMEOUT_SECONDS)
    COMPACTION_ENABLED = comp.get("enabled", COMPACTION_ENABLED)
    COMPACT_SUMMARY_CHARS = comp.get("summary_chars", COMPACT_SUMMARY_CHARS)
    COMPACT_REPORT_CHARS = comp.get("report_chars", COMPACT_REPORT_CHARS)
    COMPACT_REVIEW_CHARS = comp.get("review_chars", COMPACT_REVIEW_CHARS)
    RESEARCH_NOTE_CHARS = comp.get("research_chars", RESEARCH_NOTE_CHARS)
    DEFAULT_GATING = SETTINGS.get("gating", DEFAULT_GATING)


def activate(start: Path | None = None) -> Path | None:
    """Discover the project from `start` (default CWD), load merged settings, and set the
    module globals. Returns the project root, or None if the CWD is not inside a guild project.
    Safe to call even when uninitialized; commands that require a project check GUILD_DIR.
    """
    global PROJECT_ROOT, GUILD_DIR, RUNS_DIR, CONTEXT_PATH, PROJECT_ROLES_DIR, SETTINGS, SOURCES
    project_root = find_project_root(start)
    SETTINGS, SOURCES = resolve(project_root)
    _refresh_constants()
    if project_root is not None:
        PROJECT_ROOT = project_root
        GUILD_DIR = project_root / PROJECT_DIRNAME
        RUNS_DIR = GUILD_DIR / "runs"
        CONTEXT_PATH = GUILD_DIR / "context.md"
        PROJECT_ROLES_DIR = GUILD_DIR / "roles"
    else:
        PROJECT_ROOT = (start or Path.cwd()).resolve()
        GUILD_DIR = None
        RUNS_DIR = PROJECT_ROOT / PROJECT_DIRNAME / "runs"
        CONTEXT_PATH = None
        PROJECT_ROLES_DIR = None
    return project_root


# --- reads + writes ----------------------------------------------------------------------

def setting(dotted: str, default=None):
    """Read a dotted key (e.g. 'roles.reviewer') from the resolved SETTINGS."""
    node = SETTINGS
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def apply_overrides(overrides: dict) -> None:
    """Layer runtime (flag) overrides onto SETTINGS in memory, dotted-key -> value."""
    for dotted, value in overrides.items():
        _set_nested(SETTINGS, dotted, value)
    _refresh_constants()


def parse_value(raw: str):
    """Coerce a CLI string into a JSON scalar where possible (true/false/null/number/quoted),
    otherwise keep it as a plain string. So `set compaction.enabled false` stores a bool."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _set_nested(root: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = root
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _unset_nested(root: dict, dotted: str) -> bool:
    parts = dotted.split(".")
    node = root
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            return False
        node = nxt
    return node.pop(parts[-1], _MISSING) is not _MISSING


_MISSING = object()


def write_setting(target: Path, dotted: str, value) -> None:
    """Set a dotted key inside the JSON config file at `target`, creating it if needed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _read_json(target)
    _set_nested(data, dotted, value)
    target.write_text(json.dumps(data, indent=2) + "\n")


def unset_setting(target: Path, dotted: str) -> bool:
    """Remove a dotted key from the JSON config file at `target`. Returns False if absent."""
    if not target.exists():
        return False
    data = _read_json(target)
    if not _unset_nested(data, dotted):
        return False
    target.write_text(json.dumps(data, indent=2) + "\n")
    return True

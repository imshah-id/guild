"""Session and step state, persisted to <project>/.guild/runs/<id>/state.json.

The pipeline writes this file after every transition; the monitor reads it live. Writes are
atomic (temp file + os.replace) so a reader never sees a half-written file.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import config

# Step status values.
PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
BLOCKED = "blocked"
NEEDS_APPROVAL = "needs_approval"
SKIPPED = "skipped"

# Phases.
PLAN = "plan"
RESEARCH = "research"
IMPLEMENT = "implement"
REVIEW = "review"
TEST = "test"
FIX = "fix"


@dataclass
class Step:
    id: str
    phase: str
    title: str
    task: str = ""
    status: str = PENDING
    agent: str = ""
    run_dir: str = ""
    summary: str = ""
    verdict: str = ""
    attempts: int = 0
    needs_human: bool = False
    human_reason: str = ""
    started: float = 0.0
    ended: float = 0.0
    returncode: int | None = None

    def elapsed(self) -> float:
        if self.started == 0.0:
            return 0.0
        end = self.ended if self.ended else time.time()
        return end - self.started


@dataclass
class Session:
    id: str
    goal: str
    gating: str = config.DEFAULT_GATING
    status: str = "planning"
    created: float = field(default_factory=time.time)
    cwd: str = field(default_factory=lambda: str(config.PROJECT_ROOT))
    steps: list[Step] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return config.RUNS_DIR / self.id

    def state_path(self) -> Path:
        return self.dir / "state.json"

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path().with_name("state.json.tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2))
        os.replace(tmp, self.state_path())

    @staticmethod
    def new(goal: str, gating: str) -> "Session":
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        return Session(id=f"{stamp}-{uuid.uuid4().hex[:6]}", goal=goal, gating=gating)

    @staticmethod
    def load(session_id: str) -> "Session | None":
        """Reconstruct a Session (and its Steps) from <runs>/<id>/state.json, or None if the
        session does not exist or its state file cannot be read. Unknown keys are ignored so an
        older on-disk state still loads as the schema grows."""
        data = load_dict(config.RUNS_DIR / session_id / "state.json")
        if data is None:
            return None
        steps = [
            Step(**_only_fields(Step, raw))
            for raw in data.get("steps", [])
            if isinstance(raw, dict)
        ]
        session = Session(**_only_fields(Session, data, exclude={"steps"}))
        session.steps = steps
        return session


def _only_fields(cls, data: dict, exclude: set[str] = frozenset()) -> dict:
    """Keep only keys that are real constructor fields of `cls`, dropping anything else."""
    names = {f.name for f in fields(cls)} - set(exclude)
    return {k: v for k, v in data.items() if k in names}


def load_dict(state_path: Path) -> dict | None:
    """Read a state file as a plain dict for the read-only monitor and status command."""
    try:
        return json.loads(Path(state_path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def latest_session_dir() -> Path | None:
    if not config.RUNS_DIR.exists():
        return None
    sessions = [
        p for p in config.RUNS_DIR.iterdir()
        if p.is_dir() and (p / "state.json").exists()
    ]
    if not sessions:
        return None
    return max(sessions, key=lambda p: (p / "state.json").stat().st_mtime)

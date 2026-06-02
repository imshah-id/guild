"""Lightweight per-agent outcome tracking stored under `.guild/scorecard.json`."""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import config, state


def path() -> Path | None:
    return (config.GUILD_DIR / "scorecard.json") if config.GUILD_DIR is not None else None


def load() -> dict:
    target = path()
    if target is None:
        return {"agents": {}}
    try:
        data = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError):
        return {"agents": {}}
    return data if isinstance(data, dict) else {"agents": {}}


def save(data: dict) -> None:
    target = path()
    if target is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name("scorecard.json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, target)


def record_step(step: state.Step) -> None:
    if not step.agent:
        return
    data = load()
    agents = data.setdefault("agents", {})
    agent = agents.setdefault(step.agent, {
        "total": 0,
        "ok": 0,
        "failed": 0,
        "seconds": 0,
        "phases": {},
        "verdicts": {},
    })
    agent["total"] = int(agent.get("total", 0)) + 1
    if step.status == state.DONE:
        agent["ok"] = int(agent.get("ok", 0)) + 1
    else:
        agent["failed"] = int(agent.get("failed", 0)) + 1
    agent["seconds"] = int(agent.get("seconds", 0)) + int(step.elapsed())

    phases = agent.setdefault("phases", {})
    phase = phases.setdefault(step.phase, {"total": 0, "ok": 0})
    phase["total"] = int(phase.get("total", 0)) + 1
    if step.status == state.DONE:
        phase["ok"] = int(phase.get("ok", 0)) + 1

    if step.verdict:
        verdicts = agent.setdefault("verdicts", {})
        verdicts[step.verdict] = int(verdicts.get(step.verdict, 0)) + 1
    save(data)


def lines(data: dict | None = None) -> list[str]:
    data = data or load()
    agents = data.get("agents", {}) if isinstance(data, dict) else {}
    if not agents:
        return ["no scorecard data yet"]
    out = ["agent scorecard"]
    for name in sorted(agents):
        item = agents[name]
        total = int(item.get("total", 0))
        ok = int(item.get("ok", 0))
        failed = int(item.get("failed", 0))
        avg = int(item.get("seconds", 0)) // total if total else 0
        out.append(f"  {name:10} {ok}/{total} ok  {failed} failed  avg {avg}s")
        verdicts = item.get("verdicts", {})
        if verdicts:
            bits = ", ".join(f"{k}={v}" for k, v in sorted(verdicts.items()))
            out.append(f"    verdicts: {bits}")
    return out

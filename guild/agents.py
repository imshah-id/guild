"""Headless invocation of the agent CLIs, driven by an AgentSpec and a capability.

Command construction is split into pure `_*_cmd` builders (so they can be unit-tested without
executing anything) from the run functions that actually spawn the subprocess. Output is
streamed to files in the run dir so the monitor can tail it live. No agent is ever invoked with
a bypass or auto-approve flag, and the permission posture comes from the role's capability, not
from which CLI happens to be playing the role.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import config, context, roles
from .roles import READ_ONLY, WRITE, AgentSpec


@dataclass
class AgentResult:
    ok: bool
    text: str
    returncode: int
    run_dir: str
    duration: float


def assemble(role_brief: str, task: str) -> str:
    """Project brief + role brief + task spec: the full prompt every agent receives."""
    parts: list[str] = []
    brief = context.load_brief()
    if brief.strip():
        parts += [brief, "\n\n---\n\n"]
    parts += [role_brief, "\n\n---\n\n## Task\n\n", task, "\n"]
    return "".join(parts)


# --- pure command builders ---------------------------------------------------------------

def _claude_cmd(spec: AgentSpec, capability: str, prompt: str) -> list[str]:
    cmd = [spec.bin, "-p", prompt, "--output-format", "json"]
    if spec.model:
        cmd += ["--model", spec.model]
    if capability == READ_ONLY:
        cmd += ["--disallowedTools", "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"]
    return cmd


def _codex_cmd(spec: AgentSpec, prompt: str, result_file: Path, root: str) -> list[str]:
    cmd = [
        spec.bin, "exec",
        "-s", spec.sandbox or "workspace-write",
        "-C", root,
        "--skip-git-repo-check",
        "--json",
        "-o", str(result_file),
    ]
    if spec.model:
        cmd += ["-m", spec.model]
    if spec.effort:
        cmd += ["-c", f"model_reasoning_effort={spec.effort}"]
    cmd.append(prompt)
    return cmd


def _codex_review_cmd(spec: AgentSpec, prompt: str, result_file: Path, root: str, is_git: bool) -> list[str]:
    if is_git:
        return [spec.bin, "review", "--uncommitted", prompt]
    cmd = [spec.bin, "exec", "-s", "read-only", "-C", root, "--skip-git-repo-check",
           "-o", str(result_file)]
    if spec.model:
        cmd += ["-m", spec.model]
    cmd.append(prompt)
    return cmd


def _agy_cmd(spec: AgentSpec, prompt: str, root: str, timeout: int) -> list[str]:
    cmd = [spec.bin, "--print", "--sandbox", "--add-dir", root, "--print-timeout", f"{timeout}s"]
    if spec.model:
        cmd += ["--model", spec.model]
    cmd.append(prompt)
    return cmd


# --- subprocess plumbing -----------------------------------------------------------------

def _popen_wait(cmd: list[str], out_path: Path, err_path: Path, timeout: int) -> int:
    """Run cmd from the project root, streaming stdout/stderr to files. Returns the exit code,
    or 124 if it had to be killed on timeout."""
    out = open(out_path, "w")
    err = open(err_path, "w")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(config.PROJECT_ROOT),
            stdout=out,
            stderr=err,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return 124
    finally:
        out.close()
        err.close()


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _is_git(root: str) -> bool:
    try:
        return subprocess.run(
            ["git", "-C", root, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
        ).returncode == 0
    except OSError:
        return False


# --- adapter runners ---------------------------------------------------------------------

def _run_claude(spec: AgentSpec, capability: str, prompt: str, run_dir: Path, timeout: int) -> AgentResult:
    cmd = _claude_cmd(spec, capability, prompt)
    start = time.time()
    rc = _popen_wait(cmd, run_dir / "out.json", run_dir / "run.err", timeout)
    duration = time.time() - start
    text = ""
    raw = _read(run_dir / "out.json")
    if raw.strip():
        try:
            data = json.loads(raw)
            text = str(data.get("result", "")) if isinstance(data, dict) else raw
        except json.JSONDecodeError:
            text = raw
    (run_dir / "result.md").write_text(text)
    return AgentResult(rc == 0 and bool(text.strip()), text, rc, str(run_dir), duration)


def _run_codex(spec: AgentSpec, capability: str, prompt: str, run_dir: Path, timeout: int) -> AgentResult:
    root = str(config.PROJECT_ROOT)
    result_file = run_dir / "result.md"
    if capability == READ_ONLY:
        is_git = _is_git(root)
        cmd = _codex_review_cmd(spec, prompt, result_file, root, is_git)
        out_path = result_file if is_git else (run_dir / "run.jsonl")
        start = time.time()
        rc = _popen_wait(cmd, out_path, run_dir / "run.err", timeout)
        return AgentResult(rc == 0, _read(result_file), rc, str(run_dir), time.time() - start)
    cmd = _codex_cmd(spec, prompt, result_file, root)
    start = time.time()
    rc = _popen_wait(cmd, run_dir / "run.jsonl", run_dir / "run.err", timeout)
    return AgentResult(rc == 0, _read(result_file), rc, str(run_dir), time.time() - start)


def _run_agy(spec: AgentSpec, capability: str, prompt: str, run_dir: Path, timeout: int) -> AgentResult:
    root = str(config.PROJECT_ROOT)
    cmd = _agy_cmd(spec, prompt, root, timeout)
    start = time.time()
    rc = _popen_wait(cmd, run_dir / "result.md", run_dir / "run.err", timeout + 30)
    duration = time.time() - start
    text = _read(run_dir / "result.md")
    return AgentResult(rc == 0 and bool(text.strip()), text, rc, str(run_dir), duration)


_ADAPTERS = {
    "claude": _run_claude,
    "codex": _run_codex,
    "agy": _run_agy,
}


def run(spec: AgentSpec, capability: str, prompt: str, run_dir: Path, *, timeout: int) -> AgentResult:
    """Invoke `spec`'s CLI with the given capability. Writes prompt.md and returns the result."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "prompt.md").write_text(prompt)
    runner = _ADAPTERS.get(spec.adapter)
    if runner is None:
        return AgentResult(False, f"unknown adapter '{spec.adapter}' for agent '{spec.name}'",
                           2, str(run_dir), 0.0)
    return runner(spec, capability, prompt, run_dir, timeout)


def run_role(role: str, task: str, run_dir: Path, *, timeout: int) -> AgentResult:
    """Convenience for single-agent one-offs: resolve the role's spec, brief, and capability."""
    spec = roles.spec_for(role)
    prompt = assemble(roles.brief_for(role), task)
    return run(spec, roles.capability_for(role), prompt, run_dir, timeout=timeout)

"""The autonomous pipeline.

Executes the planned steps in order. Every implement/fix step is automatically reviewed by a
different agent than wrote it (the cross-review rule). A REQUEST-CHANGES verdict spawns a bounded
fix loop. Steps flagged needs_human, and the final acceptance, pause for the human via the
injected gate callback.

The pipeline never runs git, database, or destructive commands itself; it only invokes the agent
CLIs with safe sandboxes and the permission posture each role's capability allows.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from . import agents, compaction, config, render, roles, state
from .state import (
    BLOCKED, DONE, FAILED, FIX, IMPLEMENT, NEEDS_APPROVAL, RESEARCH, REVIEW,
    RUNNING, SKIPPED, TEST, Session, Step,
)

# gate(prompt, options) -> the chosen option string.
Gate = Callable[[str, list[str]], str]

_VERDICT = re.compile(r"\b(APPROVE-WITH-NITS|REQUEST-CHANGES|APPROVE)\b")


class PipelineAbort(RuntimeError):
    """Raised to unwind the pipeline when the human chooses to abort at a gate."""


def parse_verdict(text: str) -> str:
    match = _VERDICT.search(text.upper())
    return match.group(1) if match else "REQUEST-CHANGES"  # absence of a clear pass = caution


def _first_paragraph(text: str, limit: int = 280) -> str:
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if block:
            return block[:limit]
    return ""


class Pipeline:
    def __init__(self, session: Session, gate: Gate, *, compact: bool = True):
        self.s = session
        self.gate = gate
        self.compact = compact and config.COMPACTION_ENABLED
        self.notes: list[str] = []

    # --- run-dir + state helpers ------------------------------------------------------

    def _rundir(self, step: Step) -> Path:
        return self.s.dir / step.id

    def _save(self) -> None:
        self.s.save()

    def _begin(self, step: Step, agent: str) -> None:
        step.status = RUNNING
        step.agent = agent
        step.started = time.time()
        self._save()

    def _finish(self, step: Step, result: agents.AgentResult, *, verdict: str = "") -> None:
        step.status = DONE if result.ok else FAILED
        step.summary = (
            compaction.report(result.text, config.COMPACT_SUMMARY_CHARS)
            if self.compact else result.text[:4000]
        )
        step.returncode = result.returncode
        step.run_dir = result.run_dir
        step.verdict = verdict
        step.ended = time.time()
        self._save()
        self._print_done(step)

    def _print_done(self, step: Step) -> None:
        color = render.phase_color(step.phase)
        mark = f"{render.GREEN}ok{render.RESET}" if step.status == DONE else f"{render.RED}x {render.RESET}"
        agent = f"  {render.DIM}{step.agent}{render.RESET}" if step.agent else ""
        extra = f"  {render.DIM}{step.verdict}{render.RESET}" if step.verdict else ""
        render.say(
            f"  {mark} {color}{step.phase:9}{render.RESET} {step.title}{agent}"
            f"  {render.DIM}{int(step.elapsed())}s{render.RESET}{extra}"
        )

    # --- task assembly ----------------------------------------------------------------

    def _restore_notes(self) -> None:
        """On resume, rebuild the scout's running findings from research steps that already
        completed, so later implement steps still receive the prior context they did first time."""
        for step in self.s.steps:
            if step.phase == RESEARCH and step.status == DONE and step.summary:
                self.notes.append(
                    f"[{step.title}] {_first_paragraph(step.summary, config.RESEARCH_NOTE_CHARS)}"
                )

    def _task_with_notes(self, step: Step) -> str:
        if not self.notes:
            return step.task
        recent = "\n".join(f"- {note}" for note in self.notes[-4:])
        return f"{step.task}\n\n## Prior findings from the scout\n{recent}\n"

    def _review_task(self, impl_step: Step) -> str:
        coder_report = (
            compaction.report(impl_step.summary, config.COMPACT_REPORT_CHARS)
            if self.compact else impl_step.summary[:4000]
        )
        return (
            "Review the code the coder just wrote for the task below. Read the files it changed "
            "(its report lists them) and judge correctness and edge cases, the project's hard "
            "rules, types, security, and test coverage.\n\n"
            f"## Task that was implemented\n{impl_step.task}\n\n"
            f"## Coder's own report\n{coder_report}\n"
        )

    def _fix_task(self, step: Step, review_text: str) -> str:
        feedback = (
            compaction.review_findings(review_text, config.COMPACT_REVIEW_CHARS)
            if self.compact else review_text[:4000]
        )
        return (
            f"{step.task}\n\n## Review feedback to address\n"
            "Fix every Blocker and Major below, then briefly note what changed.\n\n"
            f"{feedback}\n"
        )

    # --- the run loop -----------------------------------------------------------------

    def run(self, *, resume: bool = False) -> None:
        self._print_plan()
        if resume:
            self._restore_notes()
        elif self.s.gating in ("guided", "checkpoint"):
            if self.gate("Approve this plan?", ["approve", "abort"]) != "approve":
                self._abort("aborted at plan gate")
                return

        self.s.status = "running"
        self._save()

        index = 0
        while index < len(self.s.steps):
            step = self.s.steps[index]
            if step.status in (DONE, SKIPPED):
                index += 1
                continue
            if not self._clear_human_gate(step):
                return  # aborted

            if step.phase == RESEARCH:
                self._do_research(step)
            elif step.phase in (IMPLEMENT, FIX):
                result_ok = self._do_implement(step)
                if result_ok:
                    self._review(step, index)
            elif step.phase == REVIEW:
                self._rerun_review(step)  # an interrupted review, picked up on resume
            elif step.phase == TEST:
                self._do_test(step, index)

            if self.s.gating == "checkpoint" and step.status == DONE:
                if self.gate(f"Finished '{step.title}'. Continue?", ["continue", "abort"]) == "abort":
                    self._abort("aborted at checkpoint")
                    return
            index += 1

        if self.s.gating in ("guided", "checkpoint"):
            self.gate(self._final_summary() + "\n  Accept and finish?", ["accept"])
        self.s.status = "done"
        self._save()
        render.say(f"\n{render.GREEN}pipeline complete{render.RESET}  {self._counts()}")
        render.say(f"{render.DIM}nothing was committed or merged; that stays with you.{render.RESET}")

    def _clear_human_gate(self, step: Step) -> bool:
        """Hard safety gate (DB, dependency, destructive). Applies in every mode. Returns
        False only if the human aborts."""
        if not step.needs_human:
            return True
        step.status = NEEDS_APPROVAL
        self._save()
        choice = self.gate(
            f"Step '{step.title}' needs approval: {step.human_reason or 'flagged by the planner'}",
            ["approve", "skip", "abort"],
        )
        if choice == "abort":
            self._abort("aborted at safety gate")
            return False
        if choice == "skip":
            step.status = SKIPPED
            self._save()
            return True
        step.needs_human = False
        step.status = state.PENDING
        self._save()
        return True

    # --- per-phase work ---------------------------------------------------------------

    def _do_research(self, step: Step) -> None:
        spec = roles.spec_for("researcher")
        self._begin(step, spec.name)
        with render.Spinner(f"{spec.name} researching: {step.title}"):
            result = agents.run(
                spec, roles.capability_for("researcher"),
                agents.assemble(roles.brief_for("researcher"), self._task_with_notes(step)),
                self._rundir(step),
                timeout=config.RESEARCH_TIMEOUT_SECONDS,
            )
        self._finish(step, result)
        if result.ok:
            self.notes.append(f"[{step.title}] {_first_paragraph(result.text, config.RESEARCH_NOTE_CHARS)}")

    def _do_implement(self, step: Step) -> bool:
        spec = roles.spec_for("implementer")
        self._begin(step, spec.name)
        with render.Spinner(f"{spec.name} implementing: {step.title}"):
            result = agents.run(
                spec, roles.capability_for("implementer"),
                agents.assemble(roles.brief_for("implementer"), self._task_with_notes(step)),
                self._rundir(step),
                timeout=config.STEP_TIMEOUT_SECONDS,
            )
        self._finish(step, result)
        return result.ok

    def _review(self, impl_step: Step, index: int) -> None:
        review = Step(
            id=f"{impl_step.id}-review",
            phase=REVIEW,
            title=f"review: {impl_step.title}",
            attempts=impl_step.attempts,
        )
        self.s.steps.insert(index + 1, review)
        self._run_review(impl_step, review)

    def _rerun_review(self, review: Step) -> None:
        """Resume entry point: a review step the loop reached that never finished. Re-drive it
        against its implement step (the review id is `<impl id>-review`)."""
        parent_id = review.id[: -len("-review")] if review.id.endswith("-review") else ""
        impl_step = next((s for s in self.s.steps if s.id == parent_id), None)
        if impl_step is None:
            review.status = SKIPPED
            self._save()
            return
        self._run_review(impl_step, review)

    def _run_review(self, impl_step: Step, review: Step) -> None:
        spec = roles.reviewer_spec(impl_step.agent)
        self._begin(review, spec.name)
        with render.Spinner(f"{spec.name} reviewing: {impl_step.title}"):
            result = agents.run(
                spec, roles.capability_for("reviewer"),
                agents.assemble(roles.brief_for("reviewer"), self._review_task(impl_step)),
                self._rundir(review),
                timeout=config.STEP_TIMEOUT_SECONDS,
            )
        verdict = parse_verdict(result.text) if result.ok else "REQUEST-CHANGES"
        self._finish(review, result, verdict=verdict)

        if verdict in ("APPROVE", "APPROVE-WITH-NITS"):
            return
        if impl_step.attempts + 1 >= config.MAX_FIX_ATTEMPTS:
            review.status = BLOCKED
            self._save()
            choice = self.gate(
                f"'{impl_step.title}' still needs changes after {impl_step.attempts + 1} attempts.",
                ["accept-anyway", "abort"],
            )
            if choice == "abort":
                self._abort("aborted after exhausting fix attempts")
                raise PipelineAbort()
            return
        fix = Step(
            id=f"{impl_step.id}-fix{impl_step.attempts + 1}",
            phase=FIX,
            title=f"fix: {impl_step.title}",
            task=self._fix_task(impl_step, result.text),
            attempts=impl_step.attempts + 1,
        )
        self.s.steps.insert(self.s.steps.index(review) + 1, fix)
        self._save()

    def _do_test(self, step: Step, index: int) -> None:
        spec = roles.spec_for("tester")
        self._begin(step, spec.name)
        with render.Spinner(f"{spec.name} testing: {step.title}"):
            result = agents.run(
                spec, roles.capability_for("tester"),
                agents.assemble(roles.brief_for("tester"), self._task_with_notes(step)),
                self._rundir(step),
                timeout=config.STEP_TIMEOUT_SECONDS,
            )
        self._finish(step, result)
        if not result.ok and step.attempts + 1 < config.MAX_FIX_ATTEMPTS:
            fix = Step(
                id=f"{step.id}-fix{step.attempts + 1}",
                phase=FIX,
                title=f"fix tests: {step.title}",
                task=self._fix_task(step, result.text),
                attempts=step.attempts + 1,
            )
            retest = Step(
                id=f"{step.id}-retest{step.attempts + 1}",
                phase=TEST,
                title=f"retest: {step.title}",
                task=step.task,
                attempts=step.attempts + 1,
            )
            self.s.steps.insert(index + 1, fix)
            self.s.steps.insert(index + 2, retest)
            self._save()

    # --- summaries --------------------------------------------------------------------

    def _abort(self, message: str) -> None:
        self.s.status = "aborted"
        self._save()
        render.say(f"{render.YELLOW}{message}{render.RESET}")

    def _print_plan(self) -> None:
        render.say(f"\n{render.BOLD}plan{render.RESET} ({len(self.s.steps)} steps)")
        for step in self.s.steps:
            flag = f"  {render.YELLOW}[needs approval]{render.RESET}" if step.needs_human else ""
            color = render.phase_color(step.phase)
            render.say(f"  - {color}{step.phase:9}{render.RESET} {step.title}{flag}")
        render.say(render.rule())

    def _counts(self) -> str:
        done = sum(1 for s in self.s.steps if s.status == DONE)
        failed = sum(1 for s in self.s.steps if s.status in (FAILED, BLOCKED))
        return f"{render.DIM}{done} done, {failed} failed/blocked, {len(self.s.steps)} total{render.RESET}"

    def _final_summary(self) -> str:
        lines = [f"\n{render.BOLD}summary{render.RESET}  {self._counts()}"]
        for step in self.s.steps:
            if step.phase == REVIEW and step.verdict:
                lines.append(f"  {render.DIM}{step.title}: {step.verdict}{render.RESET}")
        return "\n".join(lines)

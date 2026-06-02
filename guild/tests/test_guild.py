"""Tests for guild. Stdlib unittest, no network, no real agent calls.

Run from the repo root:  python3 -m unittest discover -s guild/tests -t .
Or directly:             python3 guild/tests/test_guild.py
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
import tempfile
import unittest
import argparse
from unittest import mock

# Make `import guild` work when this file is run directly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from guild import (  # noqa: E402
    agents, compaction, config, context, home, monitor, pipeline, planner, prompts, render, roles,
    scorecard, state, validation,
)
from guild.commands import completion as completion_cmd  # noqa: E402
from guild.commands import init as init_cmd  # noqa: E402
from guild.commands import plan as plan_cmd  # noqa: E402
from guild.commands import recovery as recovery_cmd  # noqa: E402
from guild.commands import report as report_cmd  # noqa: E402
from guild.commands import resume as resume_cmd  # noqa: E402
from guild.commands import run as run_cmd  # noqa: E402
from guild.commands import sessions as sessions_cmd  # noqa: E402
from guild.commands import status as status_cmd  # noqa: E402
from guild import cli as cli_mod  # noqa: E402
from guild.roles import READ_ONLY, WRITE, AgentSpec  # noqa: E402


def _fake_result(run_dir: str, text: str, ok: bool = True, rc: int = 0) -> agents.AgentResult:
    path = pathlib.Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.md").write_text(text)
    return agents.AgentResult(ok=ok, text=text, returncode=rc, run_dir=str(run_dir), duration=0.01)


class GuildTestBase(unittest.TestCase):
    """Isolates the mutable config globals and gives each test a temp runs dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._saved = {
            "SETTINGS": copy.deepcopy(config.SETTINGS),
            "SOURCES": copy.deepcopy(config.SOURCES),
            "RUNS_DIR": config.RUNS_DIR,
            "CONTEXT_PATH": config.CONTEXT_PATH,
            "GUILD_DIR": config.GUILD_DIR,
            "PROJECT_ROOT": config.PROJECT_ROOT,
            "PROJECT_ROLES_DIR": config.PROJECT_ROLES_DIR,
            "XDG": os.environ.get("XDG_CONFIG_HOME"),
        }
        config.SETTINGS = copy.deepcopy(config.DEFAULTS)
        config.SOURCES = {}
        config._refresh_constants()
        config.PROJECT_ROOT = pathlib.Path(self._tmp)
        config.RUNS_DIR = pathlib.Path(self._tmp) / "runs"
        config.CONTEXT_PATH = None
        config.GUILD_DIR = None
        config.PROJECT_ROLES_DIR = None

    def tearDown(self) -> None:
        import shutil

        config.SETTINGS = self._saved["SETTINGS"]
        config.SOURCES = self._saved["SOURCES"]
        config._refresh_constants()
        config.RUNS_DIR = self._saved["RUNS_DIR"]
        config.CONTEXT_PATH = self._saved["CONTEXT_PATH"]
        config.GUILD_DIR = self._saved["GUILD_DIR"]
        config.PROJECT_ROOT = self._saved["PROJECT_ROOT"]
        config.PROJECT_ROLES_DIR = self._saved["PROJECT_ROLES_DIR"]
        if self._saved["XDG"] is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._saved["XDG"]
        shutil.rmtree(self._tmp, ignore_errors=True)


# --- carried-over engine logic -----------------------------------------------------------

class ExtractJsonTests(unittest.TestCase):
    def test_raw_object(self) -> None:
        self.assertEqual(planner._extract_json('{"steps": []}'), {"steps": []})

    def test_fenced_block(self) -> None:
        self.assertEqual(planner._extract_json('intro\n```json\n{"a": 1}\n```\nout'), {"a": 1})

    def test_embedded_object(self) -> None:
        self.assertEqual(planner._extract_json('noise {"a": 2} trailing'), {"a": 2})


class VerdictTests(unittest.TestCase):
    def test_approve(self) -> None:
        self.assertEqual(pipeline.parse_verdict("Verdict: APPROVE"), "APPROVE")

    def test_nits_wins_over_approve(self) -> None:
        self.assertEqual(pipeline.parse_verdict("APPROVE-WITH-NITS, minor stuff"), "APPROVE-WITH-NITS")

    def test_request_changes(self) -> None:
        self.assertEqual(pipeline.parse_verdict("REQUEST-CHANGES: fix this"), "REQUEST-CHANGES")

    def test_missing_verdict_defaults_to_caution(self) -> None:
        self.assertEqual(pipeline.parse_verdict("looks fine to me"), "REQUEST-CHANGES")


class CompactionTests(unittest.TestCase):
    def test_strip_noise_removes_ansi_and_blank_runs(self) -> None:
        out = compaction.strip_noise("a\x1b[31mred\x1b[0m\n\n\n\nb")
        self.assertEqual(out, "ared\n\nb")

    def test_truncate_marks_dropped(self) -> None:
        out = compaction.truncate("x" * 100, 40)
        self.assertIn("compacted", out)
        self.assertLess(len(out), 100 + 80)

    def test_truncate_keeps_short_text_untouched(self) -> None:
        self.assertEqual(compaction.truncate("short", 40), "short")

    def test_review_findings_drops_nit_lines(self) -> None:
        review = "Major: null deref at foo.ts:10\nNit: rename x to count\nBlocker: leaks secret"
        out = compaction.review_findings(review, 500)
        self.assertIn("Major", out)
        self.assertIn("Blocker", out)
        self.assertNotIn("rename x to count", out)


class RenderTests(unittest.TestCase):
    def test_progress_bar_keeps_ratio_text(self) -> None:
        self.assertIn("1/2", render.progress(1, 2, width=4))

    def test_step_row_contains_status_phase_and_title(self) -> None:
        row = render.step_row(1, state.IMPLEMENT, state.DONE, "build it", agent="codex", verdict="APPROVE")
        self.assertIn("OK", row)
        self.assertIn("IMPLEMENT", row)
        self.assertIn("build it", row)
        self.assertIn("codex", row)


# --- config layering + discovery ---------------------------------------------------------

class ConfigLayeringTests(GuildTestBase):
    def test_precedence_default_global_project(self) -> None:
        # global config overrides gating; project config overrides a role.
        global_dir = pathlib.Path(self._tmp) / "xdg" / "guild"
        global_dir.mkdir(parents=True)
        (global_dir / "config.json").write_text(json.dumps({"gating": "hands-off"}))
        os.environ["XDG_CONFIG_HOME"] = str(pathlib.Path(self._tmp) / "xdg")

        project = pathlib.Path(self._tmp) / "proj"
        (project / ".guild").mkdir(parents=True)
        (project / ".guild" / "config.json").write_text(json.dumps({"roles": {"reviewer": "agy"}}))

        settings, sources = config.resolve(project)
        self.assertEqual(settings["gating"], "hands-off")          # from global
        self.assertEqual(settings["roles"]["reviewer"], "agy")     # from project
        self.assertEqual(settings["roles"]["planner"], "claude")   # from default
        self.assertEqual(sources["gating"], "global")
        self.assertEqual(sources["roles.reviewer"], "project")
        self.assertEqual(sources["roles.planner"], "default")

    def test_find_project_root_walks_up(self) -> None:
        project = pathlib.Path(self._tmp) / "proj"
        nested = project / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (project / ".guild").mkdir()
        self.assertEqual(config.find_project_root(nested), project.resolve())

    def test_no_project_returns_none(self) -> None:
        empty = pathlib.Path(self._tmp) / "empty"
        empty.mkdir()
        self.assertIsNone(config.find_project_root(empty))


class ConfigSetGetTests(GuildTestBase):
    def test_write_and_read_back(self) -> None:
        target = pathlib.Path(self._tmp) / "config.json"
        config.write_setting(target, "roles.reviewer", "codex")
        config.write_setting(target, "agents.codex.model", "gpt-5.5")
        data = json.loads(target.read_text())
        self.assertEqual(data["roles"]["reviewer"], "codex")
        self.assertEqual(data["agents"]["codex"]["model"], "gpt-5.5")

    def test_unset(self) -> None:
        target = pathlib.Path(self._tmp) / "config.json"
        config.write_setting(target, "gating", "hands-off")
        self.assertTrue(config.unset_setting(target, "gating"))
        self.assertNotIn("gating", json.loads(target.read_text()))
        self.assertFalse(config.unset_setting(target, "gating"))

    def test_parse_value_coercion(self) -> None:
        self.assertIs(config.parse_value("false"), False)
        self.assertEqual(config.parse_value("3"), 3)
        self.assertEqual(config.parse_value("codex"), "codex")

    def test_apply_profile_layers_runtime_settings(self) -> None:
        self.assertIsNone(config.apply_profile("fast"))
        self.assertEqual(config.setting("gating"), "hands-off")
        self.assertEqual(config.MAX_FIX_ATTEMPTS, 1)
        self.assertEqual(config.setting("agents.codex.effort"), "low")
        self.assertIn("unknown profile", config.apply_profile("missing") or "")


# --- roles + cross-review ----------------------------------------------------------------

class RoleResolutionTests(GuildTestBase):
    def test_default_mapping_and_capability(self) -> None:
        self.assertEqual(roles.spec_for("implementer").name, "codex")
        self.assertEqual(roles.spec_for("planner").name, "claude")
        self.assertEqual(roles.capability_for("reviewer"), READ_ONLY)
        self.assertEqual(roles.capability_for("implementer"), WRITE)

    def test_spec_carries_model_and_sandbox(self) -> None:
        config.SETTINGS["agents"]["codex"]["model"] = "gpt-5.5"
        spec = roles.spec_for("implementer")
        self.assertEqual(spec.model, "gpt-5.5")
        self.assertEqual(spec.sandbox, "workspace-write")

    def test_cross_review_default_differs(self) -> None:
        self.assertNotEqual(roles.reviewer_spec("codex").name, "codex")

    def test_cross_review_substitutes_when_same(self) -> None:
        config.SETTINGS["roles"]["reviewer"] = "codex"
        reviewer = roles.reviewer_spec("codex")
        self.assertNotEqual(reviewer.name, "codex")  # must be independent
        self.assertEqual(roles.cross_review_conflict(), "codex")


# --- agent command construction (no execution) -------------------------------------------

class AgentCmdTests(unittest.TestCase):
    def test_claude_read_only_locks_tools_and_passes_model(self) -> None:
        spec = AgentSpec(name="claude", bin="claude", adapter="claude", model="opus")
        cmd = agents._claude_cmd(spec, READ_ONLY, "do it")
        self.assertIn("--disallowedTools", cmd)
        self.assertIn("Bash", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("opus", cmd)
        self.assertEqual(cmd[:3], ["claude", "-p", "do it"])

    def test_claude_write_does_not_lock_tools(self) -> None:
        spec = AgentSpec(name="claude", bin="claude", adapter="claude")
        cmd = agents._claude_cmd(spec, WRITE, "do it")
        self.assertNotIn("--disallowedTools", cmd)

    def test_codex_write_passes_model_effort_sandbox(self) -> None:
        spec = AgentSpec(name="codex", bin="codex", adapter="codex",
                         model="gpt-5.5", effort="high", sandbox="workspace-write")
        cmd = agents._codex_cmd(spec, "build", pathlib.Path("/x/result.md"), "/root")
        self.assertIn("-s", cmd)
        self.assertIn("workspace-write", cmd)
        self.assertIn("-m", cmd)
        self.assertIn("gpt-5.5", cmd)
        self.assertIn("-c", cmd)
        self.assertIn("model_reasoning_effort=high", cmd)
        self.assertEqual(cmd[-1], "build")

    def test_codex_review_uses_review_subcommand_in_git(self) -> None:
        spec = AgentSpec(name="codex", bin="codex", adapter="codex")
        cmd = agents._codex_review_cmd(spec, "review it", pathlib.Path("/x/r.md"), "/root", is_git=True)
        self.assertEqual(cmd, ["codex", "review", "--uncommitted", "review it"])

    def test_agy_passes_model_and_timeout(self) -> None:
        spec = AgentSpec(name="agy", bin="agy", adapter="agy", model="gemini-3")
        cmd = agents._agy_cmd(spec, "research", "/root", 60)
        self.assertIn("--model", cmd)
        self.assertIn("gemini-3", cmd)
        self.assertIn("--print-timeout", cmd)
        self.assertIn("60s", cmd)


# --- init scaffold -----------------------------------------------------------------------

class InitScaffoldTests(GuildTestBase):
    def test_writes_template_files_without_agent_call(self) -> None:
        target = pathlib.Path(self._tmp) / "proj" / ".guild"
        written = init_cmd.write_scaffold(target, preset="minimal")
        self.assertTrue((target / "context.md").exists())
        self.assertTrue((target / "config.json").exists())
        self.assertTrue((target / "runs" / ".gitignore").exists())
        cfg = json.loads((target / "config.json").read_text())
        self.assertEqual(cfg["roles"]["planner"], "claude")
        self.assertIn(target / "context.md", written)

    def test_strict_ts_preset_seeds_rules(self) -> None:
        text = init_cmd._context_template("strict-ts")
        self.assertIn("no `any`", text)
        self.assertIn("## Build, run, test", text)


class PlannerTests(GuildTestBase):
    def test_make_plan_reads_parallel_group(self) -> None:
        session = state.Session.new("research two things", "guided")
        body = json.dumps({
            "steps": [
                {
                    "phase": "research",
                    "title": "a",
                    "task": "look at a",
                    "needs_human": False,
                    "human_reason": "",
                    "parallel_group": "scout",
                    "depends_on": ["00-prior"],
                }
            ]
        })

        with mock.patch.object(agents, "run", lambda *a, **k: _fake_result(str(session.dir / "00-plan"), body)):
            steps = planner.make_plan(session)

        self.assertEqual(steps[0].parallel_group, "scout")
        self.assertEqual(steps[0].depends_on, ["00-prior"])


class ValidationTests(unittest.TestCase):
    def test_validates_dependencies_and_split_parallel_groups(self) -> None:
        steps = [
            state.Step(id="01-research", phase=state.RESEARCH, title="a", task="a",
                       parallel_group="scout"),
            state.Step(id="02-implement", phase=state.IMPLEMENT, title="b", task="b"),
            state.Step(id="03-research", phase=state.RESEARCH, title="c", task="c",
                       parallel_group="scout", depends_on=["04-test"]),
            state.Step(id="04-test", phase=state.TEST, title="d", task="d"),
        ]

        lines = validation.issue_lines(validation.validate_steps(steps))

        self.assertTrue(any("parallel_group 'scout' is split" in line for line in lines))
        self.assertTrue(any("dependency '04-test' must appear before" in line for line in lines))

    def test_validates_clean_plan(self) -> None:
        steps = [
            state.Step(id="01-research", phase=state.RESEARCH, title="a", task="a",
                       parallel_group="scout"),
            state.Step(id="02-research", phase=state.RESEARCH, title="b", task="b",
                       parallel_group="scout"),
            state.Step(id="03-implement", phase=state.IMPLEMENT, title="c", task="c",
                       depends_on=["01-research"]),
        ]

        self.assertEqual(validation.validate_steps(steps), [])


# --- status smoke ------------------------------------------------------------------------

class StatusSmokeTests(GuildTestBase):
    def test_status_lines_render(self) -> None:
        lines = status_cmd.status_lines()
        text = "\n".join(lines)
        self.assertIn("roles -> agent", text)
        self.assertIn("gating", text)
        self.assertIn("not initialized", text)  # GUILD_DIR is None in this base


class HomeInterfaceTests(GuildTestBase):
    def test_home_lines_show_api_models_effort_and_usage(self) -> None:
        config.SETTINGS["agents"]["codex"]["model"] = "gpt-5"
        config.SETTINGS["agents"]["codex"]["effort"] = "high"

        text = "\n".join(home.home_lines())

        self.assertIn("API / CLI agents", text)
        self.assertIn("selected models", text)
        self.assertIn("effort", text)
        self.assertIn("usage", text)
        self.assertIn("gpt-5", text)
        self.assertIn("high", text)

    def test_bare_guild_opens_home_interface(self) -> None:
        with mock.patch.object(home, "open_home") as opened:
            rc = cli_mod.main([])

        self.assertEqual(rc, 0)
        opened.assert_called_once()

    def test_home_dashboard_has_command_input(self) -> None:
        text = "\n".join(home.dashboard_lines(90, home.HomeState(command="status")))

        self.assertIn("Output", text)
        self.assertIn("> status", text)
        self.assertIn("Enter run", text)

    def test_home_embedded_command_normalizes_guild_prefix(self) -> None:
        self.assertEqual(home._normalize_command("guild status"), ["status"])
        self.assertEqual(home._normalize_command("?"), ["help"])
        self.assertEqual(home._normalize_command("/profiles"), ["config", "profiles"])
        self.assertEqual(home._normalize_command("/report --open"), ["report", "--open"])

    def test_home_embedded_command_blocks_interactive_flows(self) -> None:
        lines, rc = home.run_embedded_command('run "ship it"')

        self.assertEqual(rc, 1)
        self.assertIn("needs its own terminal flow", "\n".join(lines))

    def test_home_slash_help_and_unknown_command(self) -> None:
        lines, rc = home.run_embedded_command("/help")
        self.assertEqual(rc, 0)
        self.assertIn("/status", "\n".join(lines))

        lines, rc = home.run_embedded_command("/wat")
        self.assertEqual(rc, 1)
        self.assertIn("Unknown slash command", "\n".join(lines))

    def test_home_tab_completion_handles_slash_commands(self) -> None:
        ui = home.HomeState(command="/sta")
        home._complete_command(ui)

        self.assertEqual(ui.command, "/status ")

    def test_home_execute_clear_and_quit_actions(self) -> None:
        ui = home.HomeState(command="/clear", transcript=["old output"])
        home._execute_typed(ui)
        self.assertEqual(ui.transcript, [])
        self.assertEqual(ui.message, "Output cleared.")

        ui = home.HomeState(command="/quit")
        home._execute_typed(ui)
        self.assertTrue(ui.quit_requested)

    def test_home_embedded_command_runs_safe_command(self) -> None:
        lines, rc = home.run_embedded_command("config profiles")

        self.assertEqual(rc, 0)
        self.assertIn("fast", "\n".join(lines))


# --- state round trip --------------------------------------------------------------------

class StateRoundTripTests(GuildTestBase):
    def test_save_and_load(self) -> None:
        session = state.Session.new("a goal", "guided")
        session.steps = [state.Step(id="01-implement", phase="implement", title="thing")]
        session.save()
        data = state.load_dict(session.state_path())
        assert data is not None
        self.assertEqual(data["goal"], "a goal")
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["phase"], "implement")

    def test_session_load_reconstructs_dataclasses(self) -> None:
        session = state.Session.new("ship it", "checkpoint")
        session.status = "running"
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="build", status=state.DONE),
            state.Step(id="02-test", phase="test", title="verify", task="run tests"),
        ]
        session.save()

        loaded = state.Session.load(session.id)
        assert loaded is not None
        self.assertEqual(loaded.goal, "ship it")
        self.assertEqual(loaded.gating, "checkpoint")
        self.assertEqual(loaded.status, "running")
        self.assertEqual([s.id for s in loaded.steps], ["01-implement", "02-test"])
        self.assertIsInstance(loaded.steps[0], state.Step)
        self.assertEqual(loaded.steps[0].status, state.DONE)
        self.assertEqual(loaded.steps[1].task, "run tests")

    def test_session_load_missing_returns_none(self) -> None:
        self.assertIsNone(state.Session.load("nope-does-not-exist"))

    def test_session_load_ignores_unknown_keys(self) -> None:
        session = state.Session.new("x", "guided")
        session.save()
        raw = json.loads(session.state_path().read_text())
        raw["from_a_newer_version"] = True
        raw["steps"] = [{"id": "01-implement", "phase": "implement", "title": "t", "future_field": 1}]
        session.state_path().write_text(json.dumps(raw))

        loaded = state.Session.load(session.id)
        assert loaded is not None
        self.assertEqual(loaded.steps[0].id, "01-implement")
        self.assertFalse(hasattr(loaded, "from_a_newer_version"))

    def test_session_dirs_newest_first(self) -> None:
        older = state.Session.new("old", "guided")
        older.save()
        newer = state.Session.new("new", "guided")
        newer.save()
        os.utime(older.state_path(), (100, 100))
        os.utime(newer.state_path(), (200, 200))

        ordered = state.session_dirs()
        self.assertEqual([p.name for p in ordered[:2]], [newer.id, older.id])


# --- session/report commands ------------------------------------------------------------

class SessionCommandTests(GuildTestBase):
    def test_sessions_lines_show_progress(self) -> None:
        session = state.Session.new("make the thing", "guided")
        session.status = "running"
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="build", status=state.DONE),
            state.Step(id="02-test", phase="test", title="test"),
        ]
        session.save()

        text = "\n".join(sessions_cmd.session_lines())
        self.assertIn(session.id, text)
        self.assertIn("running", text)
        self.assertIn("1/2", text)
        self.assertIn("make the thing", text)

    def test_report_markdown_includes_step_details(self) -> None:
        session = state.Session.new("ship it", "checkpoint")
        session.status = "done"
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="build",
                       status=state.DONE, agent="codex", summary="changed app.py",
                       changed_files=["app.py"], diff_stat=" app.py | 2 ++"),
            state.Step(id="01-implement-review", phase="review", title="review: build",
                       status=state.DONE, agent="claude", verdict="APPROVE"),
        ]

        text = report_cmd.markdown_report(session)
        self.assertIn(f"# guild report: {session.id}", text)
        self.assertIn("- Goal: ship it", text)
        self.assertIn("### 1. build", text)
        self.assertIn("changed app.py", text)
        self.assertIn("`app.py`", text)
        self.assertIn("app.py | 2 ++", text)
        self.assertIn("- Verdict: APPROVE", text)

    def test_resume_lines_show_next_and_interrupted_step(self) -> None:
        session = state.Session.new("resume me", "guided")
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="done", status=state.DONE),
            state.Step(id="02-test", phase="test", title="halfway", status=state.RUNNING),
        ]

        text = "\n".join(resume_cmd._resume_lines(session))
        self.assertIn("1/2 steps already done", text)
        self.assertIn("interrupted:", text)
        self.assertIn("next:", text)
        self.assertIn("halfway", text)

    def test_plan_edits_drop_move_and_set(self) -> None:
        session = state.Session.new("edit me", "guided")
        session.steps = [
            state.Step(id="01-research", phase=state.RESEARCH, title="first"),
            state.Step(id="02-test", phase=state.TEST, title="second"),
        ]
        args = argparse.Namespace(
            drop=[],
            move=[["2", "1"]],
            set=[
                ["02-test", "title=renamed"],
                ["02-test", "parallel_group=batch"],
                ["02-test", "depends_on=01-research"],
            ],
        )

        error = plan_cmd._apply_edits(session, args)

        self.assertIsNone(error)
        self.assertEqual([s.id for s in session.steps], ["02-test", "01-research"])
        self.assertEqual(session.steps[0].title, "renamed")
        self.assertEqual(session.steps[0].parallel_group, "batch")
        self.assertEqual(session.steps[0].depends_on, ["01-research"])

    def test_report_open_writes_default_report_path(self) -> None:
        session = state.Session.new("open report", "guided")
        session.steps = [state.Step(id="01-test", phase=state.TEST, title="tests", task="run")]
        session.save()

        with mock.patch.object(report_cmd, "_open_path", return_value=True) as opened:
            rc = report_cmd.cmd_report(argparse.Namespace(id=session.id, output=None, open=True))

        self.assertEqual(rc, 0)
        self.assertTrue((session.dir / "report.md").exists())
        opened.assert_called_once_with(session.dir / "report.md")

    def test_report_open_command_by_platform(self) -> None:
        path = pathlib.Path("/tmp/report.md")
        self.assertEqual(report_cmd._open_command(path, "darwin"), ["open", str(path)])
        self.assertEqual(report_cmd._open_command(path, "linux")[0], "xdg-open")

    def test_retry_resets_step_and_removes_generated_followups(self) -> None:
        session = state.Session.new("retry me", "guided")
        session.steps = [
            state.Step(id="01-implement", phase=state.IMPLEMENT, title="build",
                       status=state.DONE, agent="codex", summary="old"),
            state.Step(id="01-implement-review", phase=state.REVIEW, title="review",
                       status=state.DONE, verdict="REQUEST-CHANGES"),
            state.Step(id="01-implement-fix1", phase=state.FIX, title="fix",
                       status=state.DONE),
        ]
        session.save()

        rc = recovery_cmd.cmd_retry(argparse.Namespace(
            session=session.id, step="1", run=False, no_compact=False,
        ))
        loaded = state.Session.load(session.id)
        assert loaded is not None

        self.assertEqual(rc, 0)
        self.assertEqual(len(loaded.steps), 1)
        self.assertEqual(loaded.steps[0].status, state.PENDING)
        self.assertEqual(loaded.steps[0].summary, "")

    def test_skip_marks_step_skipped(self) -> None:
        session = state.Session.new("skip me", "guided")
        session.steps = [state.Step(id="01-test", phase=state.TEST, title="tests")]
        session.save()

        rc = recovery_cmd.cmd_skip(argparse.Namespace(
            session=session.id, step="01-test", run=False, no_compact=False,
        ))
        loaded = state.Session.load(session.id)
        assert loaded is not None

        self.assertEqual(rc, 0)
        self.assertEqual(loaded.steps[0].status, state.SKIPPED)

    def test_monitor_plain_and_json_snapshots(self) -> None:
        data = {"id": "s1", "status": "running", "goal": "g", "steps": [
            {"status": "done", "phase": "test", "title": "verify", "started": 0.0}
        ]}

        self.assertIn("session s1", "\n".join(monitor.snapshot_lines(data)))
        self.assertEqual(json.loads(monitor.snapshot_json(data))["id"], "s1")

    def test_scorecard_records_agent_outcomes(self) -> None:
        config.GUILD_DIR = pathlib.Path(self._tmp) / ".guild"
        step = state.Step(id="01-review", phase=state.REVIEW, title="review",
                          status=state.DONE, agent="claude", verdict="APPROVE")

        scorecard.record_step(step)
        data = scorecard.load()

        self.assertEqual(data["agents"]["claude"]["ok"], 1)
        self.assertIn("APPROVE=1", "\n".join(scorecard.lines(data)))

    def test_completion_scripts_include_commands(self) -> None:
        self.assertIn("guild", completion_cmd._bash())
        self.assertIn("resume", completion_cmd._fish())
        self.assertIn("--plan-only", completion_cmd._bash())
        self.assertIn("--open", completion_cmd._zsh())
        self.assertIn("-l open", completion_cmd._fish())

    def test_run_profile_override_applies_before_flags(self) -> None:
        args = argparse.Namespace(profile="fast", model=None, effort="high")
        for role in roles.ROLES:
            setattr(args, role, None)

        self.assertIsNone(run_cmd._apply_overrides(args))

        self.assertEqual(config.setting("gating"), "hands-off")
        self.assertEqual(config.setting("agents.codex.effort"), "high")


# --- pipeline engine (mocked agents) -----------------------------------------------------

class PipelineEngineTests(GuildTestBase):
    def test_implement_triggers_review_and_fix_loop(self) -> None:
        session = state.Session.new("build a thing", "guided")
        session.steps = [state.Step(id="01-implement", phase="implement", title="build it", task="do the thing")]

        review_verdicts = ["REQUEST-CHANGES: remove the any-type", "APPROVE"]

        def fake_run(spec, capability, prompt, run_dir, *, timeout):
            if capability == WRITE:
                return _fake_result(str(run_dir), "changed src/foo.ts")
            return _fake_result(str(run_dir), review_verdicts.pop(0))

        gate = lambda prompt, options: options[0]

        with mock.patch.object(agents, "run", fake_run):
            pipeline.Pipeline(session, gate).run()

        phases = [(s.phase, s.status, s.verdict) for s in session.steps]
        self.assertEqual(session.status, "done", phases)
        self.assertTrue(any(s.phase == "fix" for s in session.steps), f"no fix step created: {phases}")
        review_results = [s.verdict for s in session.steps if s.phase == "review"]
        self.assertIn("REQUEST-CHANGES", review_results)
        self.assertIn("APPROVE", review_results)
        self.assertTrue(all(s.status in ("done", "skipped") for s in session.steps), phases)

    def test_reviewer_is_a_different_agent_than_implementer(self) -> None:
        session = state.Session.new("x", "hands-off")
        session.steps = [state.Step(id="01-implement", phase="implement", title="i", task="t")]
        seen: dict[str, str] = {}

        def fake_run(spec, capability, prompt, run_dir, *, timeout):
            if capability == WRITE:
                seen["impl"] = spec.name
                return _fake_result(str(run_dir), "did it")
            seen["review"] = spec.name
            return _fake_result(str(run_dir), "APPROVE")

        with mock.patch.object(agents, "run", fake_run):
            pipeline.Pipeline(session, lambda p, o: o[0]).run()

        self.assertEqual(seen["impl"], "codex")
        self.assertNotEqual(seen["review"], seen["impl"])

    def test_abort_at_plan_gate(self) -> None:
        session = state.Session.new("goal", "guided")
        session.steps = [state.Step(id="01-implement", phase="implement", title="x", task="y")]
        pipeline.Pipeline(session, lambda prompt, options: "abort").run()
        self.assertEqual(session.status, "aborted")

    def test_resume_skips_done_steps_and_runs_the_rest(self) -> None:
        session = state.Session.new("build a thing", "guided")
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="already built",
                       task="t1", status=state.DONE, agent="codex"),
            state.Step(id="02-implement", phase="implement", title="still to build", task="t2"),
        ]

        implemented: list[str] = []

        def fake_run(spec, capability, prompt, run_dir, *, timeout):
            if capability == WRITE:
                implemented.append(prompt)
                return _fake_result(str(run_dir), "changed src/foo.ts")
            return _fake_result(str(run_dir), "APPROVE")

        def gate(prompt, options):
            # On resume the plan gate must not fire (the plan was already approved).
            self.assertNotIn("Approve this plan?", prompt)
            return options[0]

        with mock.patch.object(agents, "run", fake_run):
            pipeline.Pipeline(session, gate).run(resume=True)

        self.assertEqual(session.status, "done")
        # Only the not-yet-done step (task t2) was implemented; the done one was skipped.
        self.assertEqual(len(implemented), 1, implemented)
        self.assertIn("t2", implemented[0])
        self.assertNotIn("t1", implemented[0])
        # The skipped-over implement still has no review; the resumed one got one.
        self.assertTrue(any(s.id == "02-implement-review" for s in session.steps))
        self.assertFalse(any(s.id == "01-implement-review" for s in session.steps))

    def test_resume_redrives_an_interrupted_review(self) -> None:
        # A run that died mid-review: the implement is done, its review was left running.
        session = state.Session.new("x", "hands-off")
        session.steps = [
            state.Step(id="01-implement", phase="implement", title="built",
                       task="t", status=state.DONE, agent="codex"),
            state.Step(id="01-implement-review", phase="review", title="review: built",
                       status=state.PENDING),
        ]

        reviewed: list[str] = []

        def fake_run(spec, capability, prompt, run_dir, *, timeout):
            reviewed.append(spec.name)
            return _fake_result(str(run_dir), "APPROVE")

        with mock.patch.object(agents, "run", fake_run):
            pipeline.Pipeline(session, lambda p, o: o[0]).run(resume=True)

        self.assertEqual(session.status, "done")
        self.assertEqual(len(reviewed), 1, reviewed)        # the review re-ran, exactly once
        self.assertNotEqual(reviewed[0], "codex")           # and stayed independent of the author
        review = next(s for s in session.steps if s.phase == "review")
        self.assertEqual(review.status, state.DONE)
        self.assertEqual(review.verdict, "APPROVE")

    def test_parallel_research_group_runs_all_grouped_steps(self) -> None:
        session = state.Session.new("research", "hands-off")
        session.steps = [
            state.Step(id="01-research", phase=state.RESEARCH, title="a",
                       task="look a", parallel_group="scout"),
            state.Step(id="02-research", phase=state.RESEARCH, title="b",
                       task="look b", parallel_group="scout"),
        ]
        prompts_seen: list[str] = []

        def fake_run(spec, capability, prompt, run_dir, *, timeout):
            prompts_seen.append(prompt)
            return _fake_result(str(run_dir), f"notes from {run_dir.name}")

        with mock.patch.object(agents, "run", fake_run):
            pipeline.Pipeline(session, lambda p, o: o[0]).run()

        self.assertEqual(session.status, "done")
        self.assertEqual(len(prompts_seen), 2)
        self.assertTrue(all(s.status == state.DONE for s in session.steps))


if __name__ == "__main__":
    unittest.main(verbosity=2)

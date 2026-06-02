"""`guild init`: bootstrap a project's .guild/ directory.

Template-first: writes a starter context.md you edit, a default config.json, and a gitignore for
the run logs. With --analyze it additionally asks the planner agent (read-only) to scan the repo
and draft context.md for you. Refuses to clobber an existing .guild/ unless --force.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from .. import agents, config, prompts, render, roles


def _starter_config() -> dict:
    return {
        "roles": copy.deepcopy(config.DEFAULTS["roles"]),
        "agents": copy.deepcopy(config.DEFAULTS["agents"]),
        "gating": config.DEFAULTS["gating"],
    }


def _context_template(preset: str) -> str:
    if preset == "strict-ts":
        # Replace the generic conventions block with the strict one.
        head = prompts.CONTEXT_TEMPLATE.split("## Conventions and hard rules")[0]
        tail = prompts.CONTEXT_TEMPLATE.split("## Build, run, test")[1]
        return f"{head}{prompts.STRICT_TS_CONVENTIONS}\n## Build, run, test{tail}"
    return prompts.CONTEXT_TEMPLATE


def write_scaffold(target: Path, *, preset: str = "minimal", context_text: str | None = None) -> list[Path]:
    """Write the .guild/ scaffold under `target` (the .guild dir itself). Pure file writes; no
    agent calls. Returns the paths written."""
    import json

    target.mkdir(parents=True, exist_ok=True)
    (target / "runs").mkdir(exist_ok=True)
    (target / "roles").mkdir(exist_ok=True)

    written: list[Path] = []

    context_path = target / "context.md"
    context_path.write_text(context_text if context_text is not None else _context_template(preset))
    written.append(context_path)

    config_path = target / "config.json"
    config_path.write_text(json.dumps(_starter_config(), indent=2) + "\n")
    written.append(config_path)

    gitignore = target / ".gitignore"
    gitignore.write_text("runs/\n")
    written.append(gitignore)

    runs_keep = target / "runs" / ".gitignore"
    runs_keep.write_text("*\n!.gitignore\n")
    written.append(runs_keep)

    return written


def _analyze_context(target: Path) -> str | None:
    """Run the planner agent read-only to draft a project brief. Returns the draft, or None."""
    config.activate()  # no project yet; sets PROJECT_ROOT to CWD so the agent scans here
    spec = roles.resolve_role("planner").spec
    prompt = agents.assemble(roles.brief_for("planner"), prompts.ANALYZE_INSTRUCTIONS)
    run_dir = target / "runs" / "00-analyze"
    render.say(f"{render.DIM}analyzing the repository with {spec.name} (read-only)...{render.RESET}")
    with render.Spinner(f"{spec.name} drafting context.md"):
        result = agents.run(spec, roles.READ_ONLY, prompt, run_dir, timeout=config.PLANNER_TIMEOUT_SECONDS)
    if result.ok and result.text.strip():
        return result.text.strip() + "\n"
    render.say(f"{render.YELLOW}analyze did not produce a draft; wrote the template instead "
               f"(see {run_dir}/run.err){render.RESET}")
    return None


def cmd_init(args: argparse.Namespace) -> int:
    target = Path.cwd() / config.PROJECT_DIRNAME
    if target.exists() and not args.force:
        render.say(f"{render.YELLOW}{target} already exists.{render.RESET} Use --force to overwrite "
                   "its config.md/context, or edit the files directly.")
        return 1

    context_text: str | None = None
    if args.analyze:
        # Need the runs dir to exist for the analyze log before scaffolding the rest.
        (target / "runs").mkdir(parents=True, exist_ok=True)
        context_text = _analyze_context(target)

    written = write_scaffold(target, preset=args.preset, context_text=context_text)
    render.say(f"{render.GREEN}initialized{render.RESET} {target}")
    for path in written:
        render.say(f"  {render.DIM}wrote{render.RESET} {path.relative_to(Path.cwd())}")
    render.say("")
    render.say("next:")
    render.say(f"  1. edit {render.CYAN}{config.PROJECT_DIRNAME}/context.md{render.RESET} so the team knows the project")
    render.say(f"  2. {render.CYAN}guild status{render.RESET} to see the resolved setup")
    render.say(f"  3. {render.CYAN}guild run \"<goal>\" --plan-only{render.RESET} to preview a plan")
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("init", help="bootstrap .guild/ in the current directory")
    parser.add_argument("--analyze", action="store_true",
                        help="have the planner agent scan the repo (read-only) and draft context.md")
    parser.add_argument("--force", action="store_true", help="overwrite an existing .guild/")
    parser.add_argument("--preset", choices=["minimal", "strict-ts"], default="minimal",
                        help="conventions seed for context.md (default: minimal)")
    parser.set_defaults(func=cmd_init, needs_project=False)

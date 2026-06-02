"""`guild init`: bootstrap a project's .guild/ directory.

Template-first: writes a starter context.md you edit, a default config.json, a `rules.md` of
engineering standards, and a gitignore for the run logs. On a real terminal it walks you through
choosing which rule packs to enforce, which agent plays each role, and the gating mode (each with
a sensible default you can accept with Enter). With --analyze it additionally asks the planner
agent (read-only) to scan the repo and draft context.md for you. Refuses to clobber an existing
.guild/ unless --force.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from .. import agents, config, prompt, prompts, render, roles, rules

_GATING_DESCRIPTIONS = {
    "guided": "auto through build/review/test; pause for the plan and risky steps (recommended)",
    "hands-off": "pause only for hard safety gates (database / dependency / destructive)",
    "checkpoint": "pause after every step",
}


def _starter_config(roles_map: dict | None = None, gating: str | None = None) -> dict:
    return {
        "roles": roles_map or copy.deepcopy(config.DEFAULTS["roles"]),
        "agents": copy.deepcopy(config.DEFAULTS["agents"]),
        "gating": gating or config.DEFAULTS["gating"],
    }


def _context_template(preset: str) -> str:
    if preset == "strict-ts":
        # Replace the generic conventions block with the strict one.
        head = prompts.CONTEXT_TEMPLATE.split("## Conventions and hard rules")[0]
        tail = prompts.CONTEXT_TEMPLATE.split("## Build, run, test")[1]
        return f"{head}{prompts.STRICT_TS_CONVENTIONS}\n## Build, run, test{tail}"
    return prompts.CONTEXT_TEMPLATE


def write_scaffold(target: Path, *, preset: str = "minimal", context_text: str | None = None,
                   rule_packs=rules.DEFAULT_PACKS, roles_map: dict | None = None,
                   gating: str | None = None) -> list[Path]:
    """Write the .guild/ scaffold under `target` (the .guild dir itself). Pure file writes; no
    agent calls. Returns the paths written."""
    target.mkdir(parents=True, exist_ok=True)
    (target / "runs").mkdir(exist_ok=True)
    (target / "roles").mkdir(exist_ok=True)

    written: list[Path] = []

    context_path = target / "context.md"
    context_path.write_text(context_text if context_text is not None else _context_template(preset))
    written.append(context_path)

    rules_text = rules.render_rules(rule_packs)
    if rules_text:
        rules_path = target / "rules.md"
        rules_path.write_text(rules_text)
        written.append(rules_path)

    config_path = target / "config.json"
    config_path.write_text(json.dumps(_starter_config(roles_map, gating), indent=2) + "\n")
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
    prompt_text = agents.assemble(roles.brief_for("planner"), prompts.ANALYZE_INSTRUCTIONS)
    run_dir = target / "runs" / "00-analyze"
    render.say(f"{render.DIM}analyzing the repository with {spec.name} (read-only)...{render.RESET}")
    with render.Spinner(f"{spec.name} drafting context.md"):
        result = agents.run(spec, roles.READ_ONLY, prompt_text, run_dir, timeout=config.PLANNER_TIMEOUT_SECONDS)
    if result.ok and result.text.strip():
        return result.text.strip() + "\n"
    render.say(f"{render.YELLOW}analyze did not produce a draft; wrote the template instead "
               f"(see {run_dir}/run.err){render.RESET}")
    return None


def _agent_label(name: str) -> str:
    spec_bits = []
    if roles.installed(name):
        spec_bits.append(f"{render.GREEN}installed{render.RESET}")
    else:
        spec_bits.append(f"{render.RED}not on PATH{render.RESET}")
    return " ".join(spec_bits)


def _default_packs(args: argparse.Namespace) -> list[str]:
    if getattr(args, "no_rules", False):
        return []
    if getattr(args, "rules", None):
        return rules.normalize(str(args.rules).split(","))
    return list(rules.DEFAULT_PACKS)


def _interactive_setup(default_packs: list[str]) -> tuple[list[str], dict, str]:
    """Walk the user through rule packs, per-role agent choice, and gating. Each prompt defaults
    to the recommended value, so pressing Enter throughout yields the standard setup."""
    render.say("")
    render.say(render.section("project setup", "press Enter to accept each default"))

    packs = prompt.multi_choose(
        "engineering rules to enforce (skills)",
        rules.pack_names(), default_packs,
        descriptions={name: rules.heading(name) for name in rules.pack_names()},
    )

    roles_map: dict[str, str] = {}
    agent_options = roles.agent_names()
    agent_desc = {name: _agent_label(name) for name in agent_options}
    render.say("")
    render.say(render.section("agent assignment", "who plays each role (you can change this later "
                                                  "with `guild roles`)"))
    for role in roles.ROLES:
        default_agent = config.DEFAULTS["roles"].get(role, agent_options[0])
        chosen = prompt.choose(f"{role}  ({roles.capability_for(role)})",
                               agent_options, default_agent, descriptions=agent_desc)
        roles_map[role] = chosen

    gating = prompt.choose("gating mode", list(config.GATING_MODES),
                           config.DEFAULTS["gating"], descriptions=_GATING_DESCRIPTIONS)
    return packs, roles_map, gating


def cmd_init(args: argparse.Namespace) -> int:
    target = Path.cwd() / config.PROJECT_DIRNAME
    if target.exists() and not args.force:
        render.say(f"{render.YELLOW}{target} already exists.{render.RESET} Use --force to overwrite "
                   "its config/context, or edit the files directly.")
        return 1

    default_packs = _default_packs(args)
    if prompt.interactive() and not getattr(args, "yes", False):
        packs, roles_map, gating = _interactive_setup(default_packs)
    else:
        packs = default_packs
        roles_map = copy.deepcopy(config.DEFAULTS["roles"])
        gating = config.DEFAULTS["gating"]

    context_text: str | None = None
    if args.analyze:
        # Need the runs dir to exist for the analyze log before scaffolding the rest.
        (target / "runs").mkdir(parents=True, exist_ok=True)
        context_text = _analyze_context(target)

    written = write_scaffold(target, preset=args.preset, context_text=context_text,
                             rule_packs=packs, roles_map=roles_map, gating=gating)
    render.say("")
    render.say(f"{render.GREEN}initialized{render.RESET} {target}")
    for path in written:
        render.say(f"  {render.DIM}wrote{render.RESET} {path.relative_to(Path.cwd())}")

    render.say("")
    render.say(render.section("rules", ", ".join(packs) if packs else "none"))
    render.say(render.section("roles"))
    for role in roles.ROLES:
        render.say(render.kv(role, f"{render.CYAN}{roles_map.get(role, '')}{render.RESET}"))
    render.say(render.kv("gating", gating))

    render.say("")
    render.say("next:")
    render.say(f"  1. edit {render.CYAN}{config.PROJECT_DIRNAME}/context.md{render.RESET} so the team knows the project")
    render.say(f"  2. {render.CYAN}guild status{render.RESET} to see the resolved setup")
    render.say(f"  3. {render.CYAN}guild roles{render.RESET} to change who plays each role")
    render.say(f"  4. {render.CYAN}guild run \"<goal>\" --plan-only{render.RESET} to preview a plan")
    return 0


def default_args() -> argparse.Namespace:
    """Defaults matching the subparser, for the top-level `guild --init` shortcut."""
    return argparse.Namespace(analyze=False, force=False, preset="minimal",
                              rules=None, no_rules=False, yes=False)


def register(subparsers) -> None:
    parser = subparsers.add_parser("init", help="bootstrap .guild/ in the current directory")
    parser.add_argument("--analyze", action="store_true",
                        help="have the planner agent scan the repo (read-only) and draft context.md")
    parser.add_argument("--force", action="store_true", help="overwrite an existing .guild/")
    parser.add_argument("--preset", choices=["minimal", "strict-ts"], default="minimal",
                        help="conventions seed for context.md (default: minimal)")
    parser.add_argument("--rules", help=f"comma-separated rule packs to enforce "
                                        f"(available: {', '.join(rules.pack_names())})")
    parser.add_argument("--no-rules", action="store_true", help="do not seed any rule packs")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="accept all defaults; skip the interactive setup")
    parser.set_defaults(func=cmd_init, needs_project=False)

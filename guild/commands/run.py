"""`guild run`: autonomously pursue a goal with the team (plan, build, cross-review, test)."""
from __future__ import annotations

import argparse

from .. import config, render, roles, state, validation
from ..pipeline import Pipeline, PipelineAbort
from ..planner import PlanError, make_plan


def _interactive_gate(prompt: str, options: list[str]) -> str:
    render.say("")
    render.say(f"{render.section('gate')} {prompt}")
    labels = "/".join(options)
    while True:
        try:
            answer = input(f"  choose [{labels}]  default={options[0]}: ").strip().lower()
        except EOFError:
            return options[0]
        if answer == "":
            return options[0]
        for option in options:
            if option == answer or option.startswith(answer):
                return option
        render.say(f"  {render.DIM}pick one of: {labels}{render.RESET}")


def _apply_overrides(args: argparse.Namespace) -> str | None:
    """Layer flag overrides onto the in-memory config. Returns an error message or None."""
    overrides: dict = {}
    known = set(roles.agent_names())

    if args.profile:
        error = config.apply_profile(args.profile)
        if error:
            return error
        known = set(roles.agent_names())

    for role in roles.ROLES:
        chosen = getattr(args, role, None)
        if chosen:
            if chosen not in known:
                return f"--{role} {chosen}: not a configured agent (have: {', '.join(sorted(known))})"
            overrides[f"roles.{role}"] = chosen

    if args.model:
        for pair in args.model.split(","):
            if "=" not in pair:
                return f"--model expects agent=model pairs, got '{pair}'"
            agent, model = pair.split("=", 1)
            agent, model = agent.strip(), model.strip()
            if agent not in known:
                return f"--model {agent}=...: not a configured agent"
            overrides[f"agents.{agent}.model"] = model

    if args.effort:
        for name in known:
            overrides[f"agents.{name}.effort"] = args.effort

    config.apply_overrides(overrides)
    return None


def cmd_run(args: argparse.Namespace) -> int:
    if config.GUILD_DIR is None:
        render.say(f"{render.YELLOW}no project here.{render.RESET} Run `guild init` first.")
        return 1

    error = _apply_overrides(args)
    if error:
        render.say(f"{render.RED}{error}{render.RESET}")
        return 1

    gating = args.gating or config.setting("gating", config.DEFAULT_GATING)
    session = state.Session.new(args.goal, gating)
    session.save()
    meta = [("session", f"{render.CYAN}{session.id}{render.RESET}"), ("gating", gating)]
    if args.profile:
        meta.append(("profile", args.profile))
    render.say(render.banner("guild run", *meta))
    render.say(render.kv("watch", "guild monitor"))
    render.say(render.rule())
    try:
        with render.Spinner("planner decomposing the goal"):
            session.steps = make_plan(session)
        session.save()
    except PlanError as exc:
        render.say(f"{render.RED}planning failed:{render.RESET} {exc}")
        session.status = "failed"
        session.save()
        return 1

    issues = validation.validate_steps(session.steps)
    if issues:
        render.say("")
        render.say(render.section("plan validation"))
        for line in validation.issue_lines(issues):
            render.say(f"  {line}")
        if validation.has_errors(issues):
            render.say(f"{render.RED}planning produced an invalid plan; edit it with `guild plan {session.id}`{render.RESET}")
            session.status = "planned"
            session.save()
            return 1

    if args.plan_only:
        render.say("")
        render.say(render.section("plan", f"{len(session.steps)} steps"))
        for index, step in enumerate(session.steps, start=1):
            flag = f"  {render.YELLOW}[needs approval]{render.RESET}" if step.needs_human else ""
            render.say(render.step_row(index, step.phase, step.status, step.title, extra=flag.strip()))
        render.say("")
        render.say(render.kv("plan-only", f"session {session.id} saved; edit with `guild plan {session.id}`"))
        session.status = "planned"
        session.save()
        return 0

    try:
        Pipeline(session, _interactive_gate, compact=not args.no_compact).run()
    except PipelineAbort:
        return 1
    return 0


def register(subparsers) -> None:
    parser = subparsers.add_parser("run", help="autonomously pursue a goal with the team")
    parser.add_argument("goal")
    parser.add_argument("--gating", choices=config.GATING_MODES, default=None,
                        help="where to pause for you (default: the project's configured gating)")
    parser.add_argument("--profile", help="named config profile to apply for this run")
    parser.add_argument("--plan-only", action="store_true",
                        help="produce and print the plan, then stop before any building")
    parser.add_argument("--no-compact", action="store_true",
                        help="disable token-saving compaction of context fed between agents")
    parser.add_argument("--model", help="per-agent model overrides, e.g. codex=gpt-5.5,claude=opus")
    parser.add_argument("--effort", choices=["low", "medium", "high"],
                        help="reasoning effort override (applied where the agent supports it)")
    for role in roles.ROLES:
        parser.add_argument(f"--{role}", help=f"override the agent for the {role} role this run")
    parser.set_defaults(func=cmd_run, needs_project=True)

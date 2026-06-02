# guild

Run your installed AI coding CLIs as a coordinated team. You give `guild` a goal; a **planner**
agent decomposes it, hands the work to a **coder** agent, a **different** agent **reviews** every
change, tests run, and bounded fix loops close the gaps, pausing only at the gates you choose. You
watch it work from a structured terminal UI or a live dashboard.

No model APIs and no cloud. The agents are the plain CLIs you already have (`claude`, `codex`,
`agy`, and others you add); guild drives them as subprocesses and coordinates them through files.
Pure Python standard library, zero runtime dependencies.

## Why

One model writing and grading its own work is a blind spot. guild assigns roles by strength and
enforces a **cross-review rule**: a change is always reviewed by a different agent than wrote it.
You stay in control: nothing is committed or merged automatically, and database or destructive
steps always stop for your approval.

## Install

```sh
pipx install .            # from a checkout
# or
pip install -e .          # editable, for hacking on guild itself
```

This puts a `guild` command on your PATH. (No checkout? `python3 -m guild ...` works too.)

## Quickstart

```sh
cd your-project
guild init                # writes .guild/ (context.md + config.json) into this repo
#   guild init --analyze  # have the planner scan the repo and draft context.md for you
$EDITOR .guild/context.md # tell the team what the project is and its rules
guild status              # see the resolved setup at a glance
guild run "Add the XP ledger reducer, pure TS, with tests" --plan-only   # preview the plan
guild plan                # inspect or edit that saved plan
guild run "Add the XP ledger reducer, pure TS, with tests"               # let it build
guild sessions            # list previous runs
guild report              # print a Markdown report for the latest run
guild monitor             # live dashboard, in a second pane
guild monitor --plain     # one-shot text snapshot
guild resume              # a run stopped early? pick up where it left off
```

A run that stops short — a timeout, Ctrl-C, a sleeping laptop, or an abort at a gate — leaves its
progress in `state.json`. `guild resume` (or `guild resume <id>` for a specific session) reloads
it and re-enters the pipeline, skipping the steps that already finished; a step caught mid-flight
re-runs from scratch, and anything you already approved isn't re-asked.

For targeted recovery, use `guild retry <session> <step>` to reset one step by index or id, or
`guild skip <session> <step>` to mark one step skipped. Add `--run` to either command to resume
immediately.

## The team

| Role | Default agent | Capability | What it does |
|------|---------------|------------|--------------|
| planner | claude | read-only | decomposes the goal into an ordered plan |
| researcher | agy | read-only | investigates options before building |
| implementer | codex | write (sandboxed) | makes one cohesive change at a time |
| reviewer | claude | read-only | reviews every change (must differ from the author) |
| tester | codex | write (sandboxed) | writes and runs tests |

Roles are abstract; which CLI plays each is just configuration, so you can swap them freely. The
**capability** (read-only vs write) comes from the role, not the agent: a reviewer mapped to a
write-capable CLI still runs read-only, and a coder mapped to any CLI gets edit access within a
safe sandbox.

## Configure and toggle

Settings resolve in layers, highest wins:

```
built-in defaults  <  ~/.config/guild/config.json (global)  <  <project>/.guild/config.json  <  CLI flags
```

Toggle anything from the CLI (it edits the JSON for you):

```sh
guild config list                            # merged config + where each value came from
guild config set roles.reviewer codex        # swap who reviews
guild config set agents.codex.model gpt-5.5  # pin a model
guild config set agents.codex.effort high    # reasoning effort (where supported)
guild config set gating hands-off            # change the default gating
guild config set compaction.enabled false --global
```

Or override just for one run:

```sh
guild run "..." --reviewer agy --model codex=gpt-5.5 --effort high --gating checkpoint
guild run "..." --profile fast       # profiles: fast, careful, review-heavy
guild config profiles                # list available profiles
```

Generate completions with:

```sh
guild completion zsh
guild completion bash
guild completion fish
```

## Gating (where it stops for you)

- **guided** (default): hands-off through research, build, cross-review, fix loops, and tests, but
  pauses to approve the plan, any database / dependency / destructive step, and final acceptance.
- **hands-off**: only the hard safety gates (database / dependency / destructive).
- **checkpoint**: pause after every step.

## Terminal UI

Foreground runs use compact banners, phase chips, status marks, and progress bars so plans and
review/fix loops are easy to scan without adding dependencies. `guild monitor` keeps the live
curses dashboard, while `guild monitor --plain` and `guild monitor --json` provide script-friendly
snapshots.

## Project layout it creates

```
.guild/
  config.json     project settings (roles, agent models/efforts, gating, ...)
  context.md      the brief every agent loads (the source of truth for your project)
  roles/          optional per-project role-brief overrides (else built-ins are used)
  runs/           one dir per session (gitignored): prompt, result, logs, state.json
```

## Package layout

```
guild/
  cli.py            arg parsing + dispatch
  commands/         run, plan, retry/skip, sessions, report, status, monitor, config, init, doctor
  config.py         layered config + project discovery
  roles.py          abstract roles, role->agent resolution, cross-review rule
  agents.py         agent adapters (claude/codex/agy), capability-aware, testable cmd builders
  context.py        loads the project brief
  planner.py        the planner decomposes a goal into a JSON plan
  pipeline.py       the engine: execute, auto cross-review, fix loop, gates
  state.py          session/step model, atomic state.json
  monitor.py        live curses dashboard and plain/json snapshots (read-only)
  scorecard.py      lightweight per-agent outcome stats
  gitutil.py        read-only git status/diff reporting
  compaction.py     token-saving compaction of context fed between agents
  prompts.py        built-in role briefs, planner instructions, init templates
  tests/            stdlib unittest (no network, no real agent calls)
```

## Token economy

Context fed forward between agents (a coder report into review, review findings into a fix,
research into the next build) is compacted automatically, with no extra model calls: noise and
review nit-lines are dropped and text is truncated on clean boundaries. Full outputs always stay
on disk in each step's `result.md`. Disable with `--no-compact`; tune the limits with
`guild config set compaction.*`.

## Safety

guild never mutates git, touches the database, or runs destructive commands itself; it only invokes
the agent CLIs with safe sandboxes and never passes a bypass flag. It does run read-only git status
and diff commands for reporting. The reviewer is always a different agent than the author. Fix
loops are bounded. Database, dependency, and destructive steps stop for your approval in every
mode. Nothing is committed or merged automatically: that stays with you.

## Develop

```sh
python3 -m unittest discover -s guild/tests -t .
```

## License

MIT.

"""Built-in engineering rule packs ("skills"): naming, type safety, programming, security, and
testing standards that `guild init` can seed into a project.

They are written to `.guild/rules.md` and injected into every agent prompt alongside the project
context, so the whole team builds to the same standard and the reviewer enforces it. Plain text,
offline, zero dependencies: nothing is fetched over the network; the packs ship with guild.
"""
from __future__ import annotations

from typing import Iterable

# pack name -> (heading, ordered rule lines)
RULE_PACKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "type-safety": ("Type safety", (
        "Types must be sound: no `any`, no unchecked casts, no `@ts-ignore` / `# type: ignore` "
        "used to silence a real error.",
        "Make illegal states unrepresentable; prefer precise types, enums, and exhaustive "
        "handling over loose strings and booleans.",
        "Validate and narrow external input (IO, network, user) at the boundary before trusting it.",
        "Never weaken a type or remove a check just to make code compile or a test pass.",
    )),
    "naming": ("Naming", (
        "Names state what a thing is or does; avoid abbreviations that are not industry-standard.",
        "Match the surrounding code's casing and conventions exactly, and stay consistent across "
        "the whole change.",
        "Booleans read as predicates (is/has/should), functions are verbs, collections are plural.",
        "No misleading names: a name must not promise behaviour the code does not deliver.",
    )),
    "programming": ("Programming", (
        "One cohesive, well-scoped change at a time; keep functions small and single-purpose.",
        "No dead code, no commented-out blocks, no throwaway scaffolding left behind.",
        "Handle errors and edge cases explicitly; never swallow an exception silently.",
        "Match the existing patterns and structure; do not introduce a new style or abstraction "
        "without a reason.",
        "Do not add a dependency when the standard library or an existing utility will do.",
    )),
    "security": ("Security", (
        "Secure by default: never log, hard-code, or commit secrets, tokens, or credentials.",
        "Treat all external input as untrusted; guard against injection and unsafe deserialization.",
        "Apply least privilege; never broaden a permission or sandbox just to get something working.",
        "Never run a destructive or irreversible command without explicit human approval.",
    )),
    "testing": ("Testing", (
        "Cover the important behaviour and edge cases; tests must be deterministic and offline.",
        "Test behaviour, not implementation detail, and assert on real outcomes.",
        "Never weaken or delete an assertion to force a pass; fix the code instead.",
        "A change that alters behaviour updates or adds the tests that prove it.",
    )),
}

# What `guild init` seeds unless told otherwise: the user's "programming rules, naming, type safety".
DEFAULT_PACKS: tuple[str, ...] = ("type-safety", "naming", "programming")

ALL_PACKS: tuple[str, ...] = tuple(RULE_PACKS)


def pack_names() -> list[str]:
    return list(ALL_PACKS)


def heading(name: str) -> str:
    pack = RULE_PACKS.get(name)
    return pack[0] if pack else name


def is_pack(name: str) -> bool:
    return name in RULE_PACKS


def normalize(names: Iterable[str]) -> list[str]:
    """Keep only known pack names, in canonical order, de-duplicated."""
    requested = {str(n).strip() for n in names if str(n).strip()}
    return [name for name in ALL_PACKS if name in requested]


def render_rules(names: Iterable[str]) -> str:
    """A single Markdown rules document for the selected packs, or "" if none are selected."""
    selected = normalize(names)
    if not selected:
        return ""
    out = [
        "# Engineering rules",
        "",
        "Binding standards for every agent on this project, enforced alongside the project "
        "context. The reviewer treats a violation of these as REQUEST-CHANGES. Edit freely; "
        "regenerate the defaults any time with `guild init --force`.",
        "",
    ]
    for name in selected:
        title, lines = RULE_PACKS[name]
        out.append(f"## {title}")
        out += [f"- {line}" for line in lines]
        out.append("")
    return "\n".join(out).rstrip() + "\n"

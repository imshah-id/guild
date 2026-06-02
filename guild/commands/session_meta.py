"""Session metadata commands: labels and notes."""
from __future__ import annotations

import argparse
import re

from .. import render, state

_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _load(session_id: str) -> state.Session | None:
    if session_id == "latest":
        latest = state.latest_session_dir()
        if latest is None:
            return None
        session_id = latest.name
    return state.Session.load(session_id)


def _normalize_label(raw: str) -> str:
    return raw.strip().lstrip("#").lower()


def _parse_labels(raw_labels: list[str]) -> tuple[list[str], str | None]:
    labels: list[str] = []
    seen: set[str] = set()
    for raw in raw_labels:
        for part in raw.split(","):
            label = _normalize_label(part)
            if not label:
                continue
            if not _LABEL_RE.match(label):
                return [], f"invalid label '{part}' (use letters, numbers, dots, dashes, or underscores)"
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return labels, None


def _label_text(session: state.Session) -> str:
    return ", ".join(session.labels) if session.labels else "(none)"


def cmd_label(args: argparse.Namespace) -> int:
    session = _load(args.session)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.session}")
        return 1
    labels, error = _parse_labels(args.labels)
    if error:
        render.say(f"{render.RED}{error}{render.RESET}")
        return 1
    if not labels:
        render.out(f"{session.id}: {_label_text(session)}")
        return 0

    existing = set(session.labels)
    added = [label for label in labels if label not in existing]
    session.labels.extend(added)
    session.save()
    if added:
        render.say(f"{render.GREEN}labeled{render.RESET} {session.id}: {', '.join(added)}")
    else:
        render.say(f"{render.YELLOW}labels already present{render.RESET} {session.id}: {', '.join(labels)}")
    return 0


def cmd_unlabel(args: argparse.Namespace) -> int:
    session = _load(args.session)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.session}")
        return 1
    labels, error = _parse_labels(args.labels)
    if error:
        render.say(f"{render.RED}{error}{render.RESET}")
        return 1
    if not labels:
        render.out(f"{session.id}: {_label_text(session)}")
        return 0

    remove = set(labels)
    before = list(session.labels)
    session.labels = [label for label in session.labels if label not in remove]
    session.save()
    removed = [label for label in before if label in remove]
    if removed:
        render.say(f"{render.GREEN}removed labels{render.RESET} {session.id}: {', '.join(removed)}")
    else:
        render.say(f"{render.YELLOW}no matching labels{render.RESET} {session.id}: {', '.join(labels)}")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    session = _load(args.session)
    if session is None:
        render.say(f"{render.RED}no such session:{render.RESET} {args.session}")
        return 1
    text = " ".join(args.text).strip()
    if not text:
        if not session.notes:
            render.out(f"{session.id}: no notes")
            return 0
        render.out(f"{session.id}:")
        for note in session.notes:
            render.out(f"  - {note.text}")
        return 0

    session.notes.append(state.SessionNote(text=text))
    session.save()
    render.say(f"{render.GREEN}noted{render.RESET} {session.id}: {text}")
    return 0


def register(subparsers) -> None:
    label = subparsers.add_parser("label", help="add or show labels on a session")
    label.add_argument("session", help="session id, or 'latest'")
    label.add_argument("labels", nargs="*", help="labels to add (comma-separated is ok)")
    label.set_defaults(func=cmd_label, needs_project=True)

    unlabel = subparsers.add_parser("unlabel", help="remove labels from a session")
    unlabel.add_argument("session", help="session id, or 'latest'")
    unlabel.add_argument("labels", nargs="*", help="labels to remove")
    unlabel.set_defaults(func=cmd_unlabel, needs_project=True)

    note = subparsers.add_parser("note", help="add or show notes on a session")
    note.add_argument("session", help="session id, or 'latest'")
    note.add_argument("text", nargs=argparse.REMAINDER, help="note text to append")
    note.set_defaults(func=cmd_note, needs_project=True)

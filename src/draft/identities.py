"""Season-long league-member map. Real names never enter kb.db or notes/."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from draft.errors import DraftStateError
from draft.io import atomic_write

IDENTITIES_FILENAME = "identities.json"
_SCHEMA = 1
_ID = re.compile(r"^m(\d+)$")


# Public team name, already in architecture.md. Used only to find our
# row when identities.json has no ours flag. Never sent in a packet.
OUR_TEAM_DISPLAY = "Confidently Incorrect"


@dataclass(frozen=True)
class Member:
    member_id: str
    pseudonym: str
    display: str
    ours: bool = False


@dataclass(frozen=True)
class Identities:
    members: dict[str, Member]


def identities_path(root: Path) -> Path:
    return root / IDENTITIES_FILENAME


def default_pseudonym(member_id: str) -> str:
    match = _ID.match(member_id)
    if match:
        return f"manager-{match.group(1)}"
    return member_id


def next_member_id(members: dict[str, Member]) -> str:
    highest = 0
    for key in members:
        match = _ID.match(key)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"m{highest + 1}"


def empty_identities() -> Identities:
    return Identities(members={})


def load_identities(root: Path) -> Identities:
    path = identities_path(root)
    if not path.is_file():
        return empty_identities()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DraftStateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DraftStateError(f"{path} must contain a JSON object")
    return _parse(raw, path)


def save_identities(root: Path, table: Identities) -> None:
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "members": {
            member.member_id: _member_json(member)
            for member in sorted(table.members.values(), key=lambda m: m.member_id)
        },
    }
    atomic_write(identities_path(root), json.dumps(payload, indent=2) + "\n")


def _parse(raw: dict[str, Any], path: Path) -> Identities:
    version = raw.get("schema_version")
    if version != _SCHEMA:
        raise DraftStateError(
            f"{path} has unsupported schema_version {version!r} (expected {_SCHEMA})"
        )
    raw_members = raw.get("members")
    if not isinstance(raw_members, dict):
        raise DraftStateError(f"{path}: members must be an object")
    members: dict[str, Member] = {}
    for key, value in raw_members.items():
        if not isinstance(key, str) or not key.strip():
            raise DraftStateError(f"{path}: member ids must be non-empty strings")
        if not isinstance(value, dict):
            raise DraftStateError(f"{path}: members.{key} must be an object")
        pseudo = value.get("pseudonym", default_pseudonym(key))
        display = value.get("display", "")
        if not isinstance(pseudo, str) or not isinstance(display, str):
            raise DraftStateError(
                f"{path}: members.{key} display and pseudonym must be strings"
            )
        members[key] = Member(
            member_id=key,
            pseudonym=pseudo.strip() or default_pseudonym(key),
            display=display.strip(),
            ours=value.get("ours") is True,
        )
    return Identities(members=members)


def _member_json(member: Member) -> dict[str, Any]:
    row: dict[str, Any] = {
        "pseudonym": member.pseudonym,
        "display": member.display,
    }
    if member.ours:
        row["ours"] = True
    return row


def our_member(table: Identities) -> Member | None:
    flagged = [m for m in table.members.values() if m.ours]
    if len(flagged) > 1:
        raise DraftStateError("identities.json has more than one member with ours=true")
    if len(flagged) == 1:
        return flagged[0]
    matches = [
        m
        for m in table.members.values()
        if m.display.casefold() == OUR_TEAM_DISPLAY.casefold()
    ]
    if len(matches) > 1:
        raise DraftStateError(
            "identities.json has more than one member named "
            f"{OUR_TEAM_DISPLAY!r}; set ours=true on exactly one"
        )
    if len(matches) == 1:
        return matches[0]
    return None

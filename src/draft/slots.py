"""Draft-slot order: slot N → member id. Identity lives in identities.json."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from draft.errors import DraftStateError
from draft.identities import (
    Identities,
    Member,
    default_pseudonym,
    empty_identities,
    load_identities,
    next_member_id,
    our_member,
    save_identities,
)
from draft.io import atomic_write

SLOTS_FILENAME = "draft-slots.json"
_SCHEMA = 1


@dataclass(frozen=True)
class SlotLabel:
    pseudonym: str
    display: str
    member_id: str = ""


@dataclass(frozen=True)
class SlotMap:
    slots: dict[int, SlotLabel]
    identities: Identities = field(default_factory=empty_identities)

    def label(self, slot: int) -> SlotLabel | None:
        return self.slots.get(slot)


def slots_path(root: Path) -> Path:
    return root / SLOTS_FILENAME


def default_display(slot: int) -> str:
    return f"Slot {slot}"


def default_seat_code(slot: int) -> str:
    return f"slot-{slot}"


def empty_map() -> SlotMap:
    return SlotMap(slots={}, identities=empty_identities())


def load_order(root: Path) -> dict[int, str]:
    path = slots_path(root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DraftStateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DraftStateError(f"{path} must contain a JSON object")
    return _parse_order(raw, path)


def save_order(root: Path, order: dict[int, str]) -> None:
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "slots": {str(slot): member_id for slot, member_id in sorted(order.items())},
    }
    atomic_write(slots_path(root), json.dumps(payload, indent=2) + "\n")


def load_slots(root: Path) -> SlotMap:
    identities = load_identities(root)
    order = load_order(root)
    slots: dict[int, SlotLabel] = {}
    for slot, member_id in order.items():
        member = identities.members.get(member_id)
        if member is None:
            continue
        slots[slot] = SlotLabel(
            member_id=member.member_id,
            pseudonym=member.pseudonym,
            display=member.display,
        )
    return SlotMap(slots=slots, identities=identities)


def save_slots(root: Path, mapping: SlotMap) -> None:
    """Write both files. Identities that are not seated are kept."""
    members = dict(mapping.identities.members)
    order: dict[int, str] = {}
    for slot, label in mapping.slots.items():
        member_id = label.member_id or next_member_id(members)
        previous = members.get(member_id)
        members[member_id] = Member(
            member_id=member_id,
            pseudonym=label.pseudonym or default_pseudonym(member_id),
            display=label.display,
            ours=previous.ours if previous is not None else False,
        )
        order[slot] = member_id
    save_identities(root, Identities(members=members))
    save_order(root, order)


def save_room(root: Path, mapping: SlotMap) -> None:
    save_slots(root, mapping)


def pseudonym_for(mapping: SlotMap, slot: int) -> str:
    label = mapping.label(slot)
    if label is None or not label.pseudonym.strip():
        return default_seat_code(slot)
    return label.pseudonym.strip()


def display_for(mapping: SlotMap, slot: int, *, names: str = "display") -> str:
    if names == "pseudonym":
        return pseudonym_for(mapping, slot)
    label = mapping.label(slot)
    if label is None or not label.display.strip():
        return default_display(slot)
    return label.display.strip()


def merge_form(existing: SlotMap, form: dict[str, str], team_count: int) -> SlotMap:
    """Apply display_N / pseudonym_N. Empty display unseats the slot; member stays."""
    members = dict(existing.identities.members)
    order = {slot: label.member_id for slot, label in existing.slots.items()}
    for slot in range(1, team_count + 1):
        has_display = f"display_{slot}" in form
        has_pseudo = f"pseudonym_{slot}" in form
        if not has_display and not has_pseudo:
            continue
        seated = existing.label(slot)
        if has_display:
            display = form[f"display_{slot}"].strip()
        else:
            display = seated.display if seated else ""
        if has_display and not display:
            order.pop(slot, None)
            continue
        if seated is None:
            member_id = next_member_id(members)
            pseudo = (
                form[f"pseudonym_{slot}"].strip()
                if has_pseudo
                else default_pseudonym(member_id)
            )
            if not pseudo:
                pseudo = default_pseudonym(member_id)
            members[member_id] = Member(member_id, pseudo, display, ours=False)
            order[slot] = member_id
            continue
        pseudo = form[f"pseudonym_{slot}"].strip() if has_pseudo else seated.pseudonym
        if not pseudo:
            pseudo = default_pseudonym(seated.member_id)
        prior = members.get(seated.member_id)
        members[seated.member_id] = Member(
            seated.member_id,
            pseudo,
            display,
            ours=prior.ours if prior is not None else False,
        )
        order[slot] = seated.member_id
    slots = {
        slot: SlotLabel(
            member_id=member_id,
            pseudonym=members[member_id].pseudonym,
            display=members[member_id].display,
        )
        for slot, member_id in order.items()
        if member_id in members
    }
    return SlotMap(slots=slots, identities=Identities(members=members))


def our_slot_from(mapping: SlotMap) -> int | None:
    member = our_member(mapping.identities)
    if member is None:
        return None
    for slot, label in mapping.slots.items():
        if label.member_id == member.member_id:
            return slot
    return None


def apply_order(existing: SlotMap, member_ids: list[str], team_count: int) -> SlotMap:
    if len(member_ids) != team_count:
        raise DraftStateError(
            f"draft order must list {team_count} members (got {len(member_ids)})"
        )
    if len(set(member_ids)) != team_count:
        raise DraftStateError("draft order has a duplicate member id")
    unknown = [mid for mid in member_ids if mid not in existing.identities.members]
    if unknown:
        raise DraftStateError(f"unknown member id in draft order: {unknown[0]}")
    slots = {
        index: SlotLabel(
            member_id=member_id,
            pseudonym=existing.identities.members[member_id].pseudonym,
            display=existing.identities.members[member_id].display,
        )
        for index, member_id in enumerate(member_ids, start=1)
    }
    return SlotMap(slots=slots, identities=existing.identities)


def order_from_form(form: dict[str, str], team_count: int) -> list[str]:
    raw = form.get("order", "").strip()
    if raw:
        ids = [part.strip() for part in raw.split(",") if part.strip()]
        return ids
    ids = []
    for slot in range(1, team_count + 1):
        mid = form.get(f"member_{slot}", "").strip()
        if mid:
            ids.append(mid)
    return ids


def _parse_order(raw: dict[str, Any], path: Path) -> dict[int, str]:
    version = raw.get("schema_version")
    if version != _SCHEMA:
        raise DraftStateError(
            f"{path} has unsupported schema_version {version!r} (expected {_SCHEMA})"
        )
    raw_slots = raw.get("slots")
    if not isinstance(raw_slots, dict):
        raise DraftStateError(f"{path}: slots must be an object")
    order: dict[int, str] = {}
    for key, value in raw_slots.items():
        if not isinstance(key, str) or not key.isdigit():
            raise DraftStateError(f"{path}: slot keys must be numeric strings")
        slot = int(key)
        if slot < 1:
            raise DraftStateError(f"{path}: slot {slot} must be >= 1")
        if isinstance(value, dict):
            raise DraftStateError(
                f"{path}: slots.{key} must be a member id string, not an object. "
                "Real names belong in identities.json (D-107)."
            )
        if not isinstance(value, str) or not value.strip():
            raise DraftStateError(f"{path}: slots.{key} must be a member id")
        order[slot] = value.strip()
    return order

"""Snake-draft pick numbers from runtime team count, slot, and picks so far.

Nothing league-derived is a constant. team_count, our_slot, and rounds
come from the caller (league-settings.json + the board session).
"""

from __future__ import annotations

from draft.errors import DraftError


def slot_on_the_clock(overall: int, team_count: int) -> int:
    """1-based roster slot that owns `overall` (1-based) in a snake draft."""
    _require_overall(overall)
    _require_team_count(team_count)
    round_index = (overall - 1) // team_count
    offset = (overall - 1) % team_count
    if round_index % 2 == 0:
        return offset + 1
    return team_count - offset


def overall_pick(round_number: int, slot: int, team_count: int) -> int:
    """1-based overall pick for `slot` in 1-based `round_number`."""
    _require_team_count(team_count)
    if round_number < 1:
        raise DraftError("round_number must be >= 1")
    _require_slot(slot, team_count)
    start = (round_number - 1) * team_count
    if (round_number - 1) % 2 == 0:
        return start + slot
    return start + (team_count - slot + 1)


def next_overall(pick_count: int) -> int:
    """Overall pick number that should be recorded next (1-based)."""
    if pick_count < 0:
        raise DraftError("pick_count must be >= 0")
    return pick_count + 1


def our_overalls(our_slot: int, team_count: int, rounds: int) -> tuple[int, ...]:
    _require_team_count(team_count)
    _require_slot(our_slot, team_count)
    if rounds < 1:
        raise DraftError("rounds must be >= 1")
    return tuple(
        overall_pick(round_number, our_slot, team_count)
        for round_number in range(1, rounds + 1)
    )


def next_our_overall(
    upcoming: int, our_slot: int, team_count: int, rounds: int
) -> int | None:
    """Smallest of our overalls that is still upcoming, or None if done."""
    if upcoming < 1:
        raise DraftError("upcoming pick must be >= 1")
    for pick in our_overalls(our_slot, team_count, rounds):
        if pick >= upcoming:
            return pick
    return None


def is_snake_turn(upcoming: int, our_slot: int, team_count: int, rounds: int) -> bool:
    """True when the next two overalls are both ours (the turn)."""
    first = next_our_overall(upcoming, our_slot, team_count, rounds)
    if first != upcoming:
        return False
    second = next_our_overall(upcoming + 1, our_slot, team_count, rounds)
    return second == upcoming + 1


def draft_length(team_count: int, rounds: int) -> int:
    _require_team_count(team_count)
    if rounds < 1:
        raise DraftError("rounds must be >= 1")
    return team_count * rounds


def _require_overall(overall: int) -> None:
    if overall < 1:
        raise DraftError("overall pick must be >= 1")


def _require_team_count(team_count: int) -> None:
    if team_count < 1:
        raise DraftError("team_count must be >= 1")


def _require_slot(slot: int, team_count: int) -> None:
    if slot < 1 or slot > team_count:
        raise DraftError(f"slot must be in 1..{team_count}")

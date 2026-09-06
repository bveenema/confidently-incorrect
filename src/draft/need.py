"""Which positions still have a starting slot open. Not a league constant."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from data.league_settings import LeagueSettings
from data.pool import PooledPlayer, normalize_position
from draft.board import RecordedPick

FLEX = {"WR", "RB", "TE"}
FLEX_SLOTS = {"W/R/T", "WRT", "FLEX"}
SKIP_SLOTS = {"BN", "BENCH", "IR"}
# Dedicated-only: a filled starter slot is the cap. No backup QB/K/DST
# while other starters are open, and not on the bench either.
CAPPED = {"QB", "K", "DST"}


def slot_key(position: str) -> str:
    pos = normalize_position(position)
    if pos in FLEX_SLOTS:
        return "FLEX"
    return pos


def starter_needs(
    settings: LeagueSettings, roster: Sequence[RecordedPick]
) -> dict[str, int]:
    filled = Counter(
        normalize_position(pick.position) for pick in roster if pick.position
    )
    needs: dict[str, int] = {}
    flex_count = 0
    for slot in settings.roster_slots:
        key = slot_key(slot.position)
        if key in SKIP_SLOTS:
            continue
        if key == "FLEX":
            flex_count += slot.count
            continue
        needs[key] = max(0, slot.count - filled.get(key, 0))
    extra = 0
    for slot in settings.roster_slots:
        key = slot_key(slot.position)
        if key not in FLEX:
            continue
        extra += max(0, filled.get(key, 0) - _dedicated_count(settings, key))
    needs["FLEX"] = max(0, flex_count - min(flex_count, extra))
    return {key: count for key, count in needs.items() if count > 0 or key != "FLEX"}


def _dedicated_count(settings: LeagueSettings, position: str) -> int:
    total = 0
    for slot in settings.roster_slots:
        if slot_key(slot.position) == position:
            total += slot.count
    return total


def starters_open(needs: dict[str, int]) -> bool:
    return any(count > 0 for count in needs.values())


def accept_position(position: str, needs: dict[str, int]) -> str | None:
    """Return the need bucket this player would fill, or None."""
    pos = normalize_position(position)
    if needs.get(pos, 0) > 0:
        return pos
    if pos in FLEX and needs.get("FLEX", 0) > 0:
        return "FLEX"
    if not starters_open(needs) and pos not in CAPPED:
        return "BN"
    return None


def eligible(
    available: Sequence[PooledPlayer],
    settings: LeagueSettings,
    roster: Sequence[RecordedPick],
) -> tuple[PooledPlayer, ...]:
    needs = starter_needs(settings, roster)
    kept = [p for p in available if accept_position(p.position, needs) is not None]
    if kept:
        return tuple(kept)
    return tuple(available)


def consume(needs: dict[str, int], bucket: str) -> None:
    if bucket not in needs:
        return
    needs[bucket] = max(0, needs[bucket] - 1)
    if needs[bucket] == 0 and bucket != "BN":
        needs.pop(bucket, None)

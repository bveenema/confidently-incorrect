"""Tier-based best-available slate when the council cannot decide (D-49)."""

from __future__ import annotations

from collections.abc import Sequence

from data.league_settings import LeagueSettings
from data.pool import PooledPlayer
from draft.board import RecordedPick
from draft.need import accept_position, consume, starter_needs

MIN_SLATE = 5


def tier_best_available(
    available: Sequence[PooledPlayer],
    *,
    n: int = MIN_SLATE,
    settings: LeagueSettings | None = None,
    roster: Sequence[RecordedPick] = (),
) -> tuple[PooledPlayer, ...]:
    """Rank remaining players by our value rank, then projection.

    When `settings` is given, fill open starter slots first (D-109). A
    second QB is not recommended once the QB slot is filled. Returns
    fewer than `n` only when the board is that thin — never pads.
    """
    ranked = _rank(available)
    if settings is None:
        return tuple(ranked[:n])
    needs = starter_needs(settings, roster)
    picked: list[PooledPlayer] = []
    for player in ranked:
        if len(picked) >= n:
            break
        bucket = accept_position(player.position, needs)
        if bucket is None:
            continue
        picked.append(player)
        consume(needs, bucket)
    return tuple(picked)


def _rank(available: Sequence[PooledPlayer]) -> list[PooledPlayer]:
    ranked = [p for p in available if p.value_rank is not None]
    ranked.sort(key=lambda p: p.value_rank or 0)
    rest = [p for p in available if p.value_rank is None]
    rest.sort(key=lambda p: (-_points(p), p.position, p.name))
    return ranked + rest


def _points(player: PooledPlayer) -> float:
    if isinstance(player.fp_points, (int, float)) and not isinstance(
        player.fp_points, bool
    ):
        return float(player.fp_points)
    if isinstance(player.tank_points, (int, float)) and not isinstance(
        player.tank_points, bool
    ):
        return float(player.tank_points)
    return 0.0

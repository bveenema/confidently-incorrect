"""Tier-based best-available slate when the council cannot decide (D-49)."""

from __future__ import annotations

from collections.abc import Sequence

from data.pool import PooledPlayer

MIN_SLATE = 5


def tier_best_available(
    available: Sequence[PooledPlayer], *, n: int = MIN_SLATE
) -> tuple[PooledPlayer, ...]:
    """Rank remaining players by our value rank, then projection.

    Returns fewer than `n` only when the board is that thin — never pads.
    """
    ranked = [p for p in available if p.value_rank is not None]
    ranked.sort(key=lambda p: p.value_rank or 0)
    rest = [p for p in available if p.value_rank is None]
    rest.sort(key=lambda p: (-_points(p), p.position, p.name))
    return tuple((ranked + rest)[:n])


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

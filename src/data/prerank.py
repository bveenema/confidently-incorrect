"""Pre-rank cheat sheet for Yahoo manual entry.

Issue 13 / D-100. Order is league-scored value_rank (D-88), not ADP.
There is no Yahoo ranking API — Ben pastes this list by hand (A-7).
"""

from __future__ import annotations

from data.errors import DataConfigError
from data.pool import PlayerPool, PooledPlayer

# Export size from issue 13, not a league-derived value.
DEFAULT_LIMIT = 200


def select_prerank(
    pool: PlayerPool, limit: int = DEFAULT_LIMIT
) -> tuple[PooledPlayer, ...]:
    """Top complete-scoring players by value_rank. Incomplete K/DST omitted."""
    if limit < 1:
        raise DataConfigError("pre-rank limit must be >= 1")
    ranked = pool.by_value_rank()
    if not ranked:
        raise DataConfigError(
            "player pool has no complete-scoring value ranks. "
            "K/DST lines are incomplete (A-13) and cannot fill a pre-rank sheet."
        )
    return ranked[:limit]


def format_prerank(rows: tuple[PooledPlayer, ...], pool: PlayerPool) -> str:
    """Numbered TSV: rank, name, position, team. Header states league scoring."""
    omitted = sum(1 for player in pool.players if player.scoring_incomplete)
    lines = [
        "# Pre-rank sheet — enter top to bottom in Yahoo (no API)",
        "# Ordered by this league's scoring, not published ADP",
        f"# season={pool.season} listed={len(rows)} "
        f"omitted_incomplete={omitted} adp_scoring={pool.adp_scoring}",
        "# Incomplete K/DST are omitted — provider lines cannot score this league.",
    ]
    for player in rows:
        rank = player.value_rank
        if rank is None:
            raise DataConfigError(
                f"pre-rank row {player.name!r} has no value_rank; "
                "select_prerank must only return ranked players"
            )
        lines.append(f"{rank}\t{player.name}\t{player.position}\t{player.team}")
    return "\n".join(lines)

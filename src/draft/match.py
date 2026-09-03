"""Resolve a typed pick onto player-pool rows.

Order: yahoo_id, exact normalized name, unique last name, DST team
abbreviation. Multiple hits are returned as candidates — never guessed.
"""

from __future__ import annotations

from collections.abc import Sequence

from data.pool import PooledPlayer, normalize_name, normalize_team


def match_players(
    players: Sequence[PooledPlayer], query: str
) -> tuple[PooledPlayer, ...]:
    q = query.strip()
    if not q:
        return ()

    by_id = tuple(p for p in players if p.yahoo_id and p.yahoo_id == q)
    if by_id:
        return by_id

    norm = normalize_name(q)
    if norm:
        exact = tuple(p for p in players if normalize_name(p.name) == norm)
        if exact:
            return exact

        last = norm.split()[-1]
        last_hits = tuple(
            p for p in players if _last_token(normalize_name(p.name)) == last
        )
        if len(last_hits) == 1:
            return last_hits
        if len(norm.split()) == 1 and last_hits:
            return last_hits

    team = normalize_team(q)
    dst = tuple(p for p in players if p.position == "DST" and p.team == team)
    if dst:
        return dst
    return ()


def find_by_key(players: Sequence[PooledPlayer], key: str) -> PooledPlayer | None:
    for player in players:
        if player_key(player) == key:
            return player
    return None


def player_key(player: PooledPlayer) -> str:
    if player.yahoo_id:
        return f"yahoo:{player.yahoo_id}"
    if player.fpid is not None:
        return f"fpid:{player.fpid}"
    if player.tank_id:
        return f"tank:{player.tank_id}"
    name = normalize_name(player.name)
    return f"ntp:{name}|{player.team}|{player.position}"


def _last_token(name: str) -> str:
    parts = name.split()
    return parts[-1] if parts else ""

"""Walk Yahoo's nested Fantasy JSON without assuming a league shape."""

from __future__ import annotations

from typing import Any

from yahoo.errors import YahooAPIError


def find_values(obj: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(obj, dict):
        if key in obj:
            found.append(obj[key])
        for value in obj.values():
            found.extend(find_values(value, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_values(item, key))
    return found


def unique_strs(obj: Any, key: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in find_values(obj, key):
        if value is None:
            continue
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            found.append(text)
    return found


def first_str(obj: Any, key: str) -> str:
    values = unique_strs(obj, key)
    if not values:
        raise YahooAPIError(f"Yahoo payload had no {key}")
    return values[0]


def league_key_from_team_key(team_key: str) -> str:
    parts = team_key.split(".")
    if len(parts) >= 3 and parts[1] == "l":
        return ".".join(parts[:3])
    raise YahooAPIError(f"cannot derive league_key from team_key {team_key!r}")


def parse_own_team(payload: dict[str, Any]) -> dict[str, str]:
    keys = unique_strs(payload, "team_key")
    if not keys:
        raise YahooAPIError("Yahoo payload had no team_key")
    if len(keys) > 1:
        raise YahooAPIError(f"Yahoo account has {len(keys)} NFL teams; refuse to guess")
    team_key = keys[0]
    return {
        "team_key": team_key,
        "league_key": league_key_from_team_key(team_key),
        "team_id": _optional_str(payload, "team_id"),
    }


def parse_league_settings(payload: dict[str, Any]) -> dict[str, Any]:
    num_teams = _first_int(payload, "num_teams")
    roster_positions = find_values(payload, "roster_position")
    stats = find_values(payload, "stat")
    return {
        "league_key": _optional_str(payload, "league_key"),
        "num_teams": num_teams,
        "roster_position_count": len(roster_positions),
        "scoring_stat_count": len(stats),
    }


def parse_roster(payload: dict[str, Any]) -> list[dict[str, str]]:
    players: list[dict[str, str]] = []
    seen: set[str] = set()
    for player_key in find_values(payload, "player_key"):
        text = str(player_key)
        if not text or text in seen:
            continue
        seen.add(text)
        players.append({"player_key": text})
    return players


def _optional_str(obj: Any, key: str) -> str:
    try:
        return first_str(obj, key)
    except YahooAPIError:
        return ""


def _first_int(obj: Any, key: str) -> int | None:
    for value in find_values(obj, key):
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None

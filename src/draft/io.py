"""Persist draft-board.json and an optional player-pool snapshot.

Both files live under $CI_STATE_DIR. Writes are atomic (temp + replace).
A failed write raises; it is never swallowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.board import DraftBoard, RecordedPick, new_board, sync_settings
from draft.errors import DraftConfigError, DraftStateError

BOARD_FILENAME = "draft-board.json"
POOL_SNAPSHOT_FILENAME = "player-pool.json"
_BOARD_SCHEMA = 1
_POOL_SCHEMA = 1


def board_path(root: Path) -> Path:
    return root / BOARD_FILENAME


def pool_snapshot_path(root: Path) -> Path:
    return root / POOL_SNAPSHOT_FILENAME


def load_board(root: Path, team_count: int, rounds: int) -> DraftBoard:
    path = board_path(root)
    if not path.exists():
        return new_board(team_count, rounds)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DraftStateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DraftStateError(f"{path} must contain a JSON object")
    return _parse_board(raw, path, team_count, rounds)


def save_board(root: Path, board: DraftBoard) -> None:
    payload = {
        "schema_version": _BOARD_SCHEMA,
        "team_count": board.team_count,
        "rounds": board.rounds,
        "our_slot": board.our_slot,
        "picks": [_pick_to_json(pick) for pick in board.picks],
    }
    _atomic_write(board_path(root), json.dumps(payload, indent=2) + "\n")


def load_pool_snapshot(path: Path) -> PlayerPool:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DraftConfigError(f"missing player-pool snapshot: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DraftConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DraftConfigError(f"{path} must contain a JSON object")
    version = raw.get("schema_version")
    if version != _POOL_SCHEMA:
        raise DraftConfigError(
            f"{path} has unsupported schema_version {version!r} "
            f"(expected {_POOL_SCHEMA})"
        )
    season = raw.get("season")
    adp = raw.get("adp_scoring")
    rows = raw.get("players")
    if not isinstance(season, int) or isinstance(season, bool):
        raise DraftConfigError(f"{path}: season must be an integer")
    if not isinstance(adp, str) or not adp.strip():
        raise DraftConfigError(f"{path}: adp_scoring must be a non-empty string")
    if not isinstance(rows, list) or not rows:
        raise DraftConfigError(f"{path}: players must be a non-empty array")
    players = tuple(
        _player_from_json(item, path, index) for index, item in enumerate(rows)
    )
    return PlayerPool(
        season=season,
        adp_scoring=adp,
        players=players,
        qb_inflation=QbInflationCheck(
            ok=True,
            median_gap=None,
            top_qbs=(),
            detail="loaded from snapshot",
        ),
    )


def save_pool_snapshot(path: Path, pool: PlayerPool) -> None:
    payload = {
        "schema_version": _POOL_SCHEMA,
        "season": pool.season,
        "adp_scoring": pool.adp_scoring,
        "players": [_player_to_json(player) for player in pool.players],
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _parse_board(
    raw: dict[str, Any], path: Path, team_count: int, rounds: int
) -> DraftBoard:
    version = raw.get("schema_version")
    if version != _BOARD_SCHEMA:
        raise DraftStateError(
            f"{path} has unsupported schema_version {version!r} "
            f"(expected {_BOARD_SCHEMA})"
        )
    stored_teams = raw.get("team_count")
    stored_rounds = raw.get("rounds")
    our_slot = raw.get("our_slot")
    raw_picks = raw.get("picks")
    if (
        not isinstance(stored_teams, int)
        or isinstance(stored_teams, bool)
        or stored_teams < 1
    ):
        raise DraftStateError(f"{path}: team_count must be an integer >= 1")
    if (
        not isinstance(stored_rounds, int)
        or isinstance(stored_rounds, bool)
        or stored_rounds < 1
    ):
        raise DraftStateError(f"{path}: rounds must be an integer >= 1")
    if our_slot is not None and (
        not isinstance(our_slot, int) or isinstance(our_slot, bool) or our_slot < 1
    ):
        raise DraftStateError(f"{path}: our_slot must be an integer >= 1 or null")
    if not isinstance(raw_picks, list):
        raise DraftStateError(f"{path}: picks must be an array")
    picks = tuple(
        _pick_from_json(item, path, index) for index, item in enumerate(raw_picks)
    )
    board = DraftBoard(
        team_count=stored_teams,
        rounds=stored_rounds,
        our_slot=our_slot,
        picks=picks,
    )
    return sync_settings(board, team_count, rounds)


def _pick_to_json(pick: RecordedPick) -> dict[str, Any]:
    return {
        "overall": pick.overall,
        "slot": pick.slot,
        "kind": pick.kind,
        "ours": pick.ours,
        "player_key": pick.player_key,
        "name": pick.name,
        "position": pick.position,
        "team": pick.team,
    }


def _pick_from_json(item: Any, path: Path, index: int) -> RecordedPick:
    prefix = f"{path}: picks[{index}]"
    if not isinstance(item, dict):
        raise DraftStateError(f"{prefix} must be an object")
    overall = item.get("overall")
    slot = item.get("slot")
    kind = item.get("kind")
    ours = item.get("ours")
    if not isinstance(overall, int) or isinstance(overall, bool) or overall < 1:
        raise DraftStateError(f"{prefix}.overall must be an integer >= 1")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1:
        raise DraftStateError(f"{prefix}.slot must be an integer >= 1")
    if kind not in {"player", "unnamed"}:
        raise DraftStateError(f"{prefix}.kind must be 'player' or 'unnamed'")
    if not isinstance(ours, bool):
        raise DraftStateError(f"{prefix}.ours must be a boolean")
    if kind == "player":
        key = item.get("player_key")
        name = item.get("name")
        if not isinstance(key, str) or not key.strip():
            raise DraftStateError(f"{prefix}.player_key is required for a player pick")
        if not isinstance(name, str) or not name.strip():
            raise DraftStateError(f"{prefix}.name is required for a player pick")
        position = item.get("position")
        team = item.get("team")
        if not isinstance(position, str) or not isinstance(team, str):
            raise DraftStateError(f"{prefix}.position and team must be strings")
        return RecordedPick(
            overall=overall,
            slot=slot,
            kind=kind,
            ours=ours,
            player_key=key,
            name=name,
            position=position,
            team=team,
        )
    return RecordedPick(overall=overall, slot=slot, kind=kind, ours=ours)


def _player_to_json(player: PooledPlayer) -> dict[str, Any]:
    return {
        "name": player.name,
        "position": player.position,
        "team": player.team,
        "yahoo_id": player.yahoo_id,
        "fpid": player.fpid,
        "tank_id": player.tank_id,
        "fp_points": player.fp_points,
        "tank_points": player.tank_points,
        "source_delta": player.source_delta,
        "value_rank": player.value_rank,
        "pos_rank": player.pos_rank,
        "adp": player.adp,
        "adp_delta": player.adp_delta,
        "tier": player.tier,
        "tier_break_after": player.tier_break_after,
        "scoring_incomplete": player.scoring_incomplete,
        "join": player.join,
    }


def _player_from_json(item: Any, path: Path, index: int) -> PooledPlayer:
    prefix = f"{path}: players[{index}]"
    if not isinstance(item, dict):
        raise DraftConfigError(f"{prefix} must be an object")
    name = item.get("name")
    position = item.get("position")
    team = item.get("team")
    if not isinstance(name, str) or not name.strip():
        raise DraftConfigError(f"{prefix}.name must be a non-empty string")
    if not isinstance(position, str) or not position.strip():
        raise DraftConfigError(f"{prefix}.position must be a non-empty string")
    if not isinstance(team, str) or not team.strip():
        raise DraftConfigError(f"{prefix}.team must be a non-empty string")
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
        yahoo_id=_opt_str(item.get("yahoo_id")),
        fpid=_opt_int(item.get("fpid")),
        tank_id=_opt_str(item.get("tank_id")),
        fp_points=_opt_num(item.get("fp_points")),
        tank_points=_opt_num(item.get("tank_points")),
        source_delta=_opt_num(item.get("source_delta")),
        value_rank=_opt_int(item.get("value_rank")),
        pos_rank=_opt_int(item.get("pos_rank")),
        adp=_opt_num(item.get("adp")),
        adp_delta=_opt_num(item.get("adp_delta")),
        tier=_opt_int(item.get("tier")),
        tier_break_after=bool(item.get("tier_break_after", False)),
        scoring_incomplete=bool(item.get("scoring_incomplete", False)),
        join=str(item.get("join") or "snapshot"),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _opt_num(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise DraftStateError(f"failed writing {path}: {exc}") from exc

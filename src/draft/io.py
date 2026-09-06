"""Persist draft-board.json and an optional player-pool snapshot.

Both files live under $CI_STATE_DIR. Writes are atomic (temp + replace).
A failed write raises; it is never swallowed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from data.errors import DataConfigError
from data.pool import (
    POOL_SNAPSHOT_SCHEMA,
    PlayerPool,
    PooledPlayer,
)
from data.pool import (
    load_pool_snapshot as load_data_pool_snapshot,
)
from draft.board import DraftBoard, RecordedPick, new_board, sync_settings
from draft.errors import DraftConfigError, DraftStateError

BOARD_FILENAME = "draft-board.json"
_BOARD_SCHEMA = 1


def board_path(root: Path) -> Path:
    return root / BOARD_FILENAME


def load_board(root: Path, team_count: int, rounds: int) -> DraftBoard:
    path = board_path(root)
    if not path.exists():
        return new_board(team_count, rounds)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
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
        return load_data_pool_snapshot(path)
    except DataConfigError as exc:
        raise DraftConfigError(str(exc)) from exc


def save_pool_snapshot(path: Path, pool: PlayerPool) -> None:
    payload = {
        "schema_version": POOL_SNAPSHOT_SCHEMA,
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


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise DraftStateError(f"failed writing {path}: {exc}") from exc

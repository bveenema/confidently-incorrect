from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.test_league_settings import _minimal, _write

from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.board import (
    advance_unnamed,
    new_board,
    record_player,
    set_our_slot,
    sync_settings,
    undo_last,
)
from draft.errors import DraftStateError
from draft.io import load_board, load_pool_snapshot, save_board, save_pool_snapshot
from draft.match import player_key


def _player(name: str, yahoo_id: str, *, position: str = "RB") -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position=position,
        team="PHI",
        yahoo_id=yahoo_id,
        fpid=None,
        tank_id=None,
        fp_points=20,
        tank_points=18,
        source_delta=2,
        value_rank=2,
        pos_rank=1,
        adp=5.0,
        adp_delta=3.0,
        tier=1,
        tier_break_after=False,
        scoring_incomplete=False,
        join="yahoo_id",
    )


def test_record_filters_available_and_tracks_ours() -> None:
    a = _player("Alpha", "1")
    b = _player("Bravo", "2", position="WR")
    board = set_our_slot(new_board(8, 3), 1)
    board = record_player(board, a)
    assert board.upcoming == 2
    assert board.on_the_clock() == 2
    assert board.our_roster()[0].name == "Alpha"
    assert board.available((a, b)) == (b,)
    assert board.turn() is False


def test_unnamed_advance_keeps_player_available() -> None:
    player = _player("Alpha", "1")
    board = set_our_slot(new_board(8, 2), 8)
    board = advance_unnamed(board)
    assert board.upcoming == 2
    assert player_key(player) not in board.drafted_keys()
    assert board.available((player,)) == (player,)


def test_turn_and_undo() -> None:
    board = set_our_slot(new_board(8, 2), 8)
    for _ in range(7):
        board = advance_unnamed(board)
    assert board.upcoming == 8
    assert board.turn()
    assert board.next_ours() == 8
    board = record_player(board, _player("Alpha", "1"))
    assert board.upcoming == 9
    assert board.turn() is False
    assert board.next_ours() == 9
    board = undo_last(board)
    assert board.upcoming == 8
    assert board.turn()


def test_rejects_duplicate_and_complete() -> None:
    player = _player("Alpha", "1")
    board = set_our_slot(new_board(2, 1), 1)
    board = record_player(board, player)
    with pytest.raises(DraftStateError, match="already drafted"):
        record_player(board, player)
    other = _player("Bravo", "2")
    board = record_player(board, other)
    assert board.complete
    with pytest.raises(DraftStateError, match="complete"):
        advance_unnamed(board)


def test_slot_required_and_immutable_after_picks() -> None:
    board = new_board(8, 15)
    with pytest.raises(DraftStateError, match="slot"):
        record_player(board, _player("Alpha", "1"))
    board = set_our_slot(board, 3)
    board = advance_unnamed(board)
    with pytest.raises(DraftStateError, match="cannot change"):
        set_our_slot(board, 4)


def test_sync_settings_fails_loud_after_picks() -> None:
    board = set_our_slot(new_board(8, 15), 2)
    board = advance_unnamed(board)
    with pytest.raises(DraftStateError, match="changed after"):
        sync_settings(board, 10, 15)


def test_roundtrip_board_and_snapshot(tmp_path: Path) -> None:
    player = _player("Alpha", "1")
    board = set_our_slot(new_board(8, 3), 1)
    board = record_player(board, player)
    save_board(tmp_path, board)
    loaded = load_board(tmp_path, 8, 3)
    assert loaded.our_slot == 1
    assert loaded.picks[0].name == "Alpha"
    assert loaded.picks[0].ours

    pool = PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=(player,),
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )
    snap = tmp_path / "player-pool.json"
    save_pool_snapshot(snap, pool)
    restored = load_pool_snapshot(snap)
    assert restored.players[0].name == "Alpha"
    assert restored.season == 2026


def test_corrupt_board_fails_loud(tmp_path: Path) -> None:
    (tmp_path / "draft-board.json").write_text("{", encoding="utf-8")
    with pytest.raises(DraftStateError, match="invalid JSON"):
        load_board(tmp_path, 8, 3)


def test_settings_mismatch_on_load(tmp_path: Path) -> None:
    board = set_our_slot(new_board(8, 3), 1)
    board = advance_unnamed(board)
    save_board(tmp_path, board)
    with pytest.raises(DraftStateError, match="changed after"):
        load_board(tmp_path, 10, 3)


def test_minimal_settings_can_be_snake(tmp_path: Path) -> None:
    payload = _minimal(10)
    payload["draft"] = {"rounds": 15, "type": "snake"}
    path = _write(tmp_path, payload)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["team_count"] == 10
    assert raw["draft"]["type"] == "snake"

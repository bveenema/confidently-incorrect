from __future__ import annotations

from pathlib import Path

from tests.test_league_settings import _minimal, _write

from data.league_settings import load_league_settings
from data.pool import PooledPlayer
from draft.board import RecordedPick
from draft.fallback import tier_best_available
from draft.need import accept_position, starter_needs
from draft.packet import council_pool_keys
from draft.recompute import _need_limited_items


def _player(name: str, yahoo_id: str, *, rank: int, position: str) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position=position,
        team="BUF",
        yahoo_id=yahoo_id,
        fpid=int(yahoo_id),
        tank_id=None,
        fp_points=100 - rank,
        tank_points=90 - rank,
        source_delta=10,
        value_rank=rank,
        pos_rank=rank,
        adp=float(rank + 4),
        adp_delta=float(4 - rank),
        tier=1,
        tier_break_after=False,
        scoring_incomplete=False,
        join="yahoo_id",
    )


def _settings(tmp_path: Path):
    payload = _minimal(8)
    payload["draft"] = {"rounds": 15, "type": "snake"}
    payload["roster_slots"] = [
        {"position": "QB", "count": 1},
        {"position": "RB", "count": 2},
        {"position": "WR", "count": 2},
        {"position": "TE", "count": 1},
        {"position": "W/R/T", "count": 1},
        {"position": "K", "count": 1},
        {"position": "DEF", "count": 1},
        {"position": "BN", "count": 6},
    ]
    _write(tmp_path, payload)
    return load_league_settings(tmp_path)


def _pick(name: str, position: str, yahoo_id: str) -> RecordedPick:
    return RecordedPick(
        overall=1,
        slot=1,
        kind="player",
        ours=True,
        player_key=f"yahoo:{yahoo_id}",
        name=name,
        position=position,
        team="BUF",
    )


def test_second_qb_is_not_needed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    needs = starter_needs(settings, (_pick("Allen", "QB", "1"),))
    assert needs.get("QB", 0) == 0
    assert accept_position("QB", needs) is None
    assert accept_position("RB", needs) == "RB"


def test_fallback_skips_qb_once_the_slot_is_filled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    players = (
        _player("Hurts", "2", rank=1, position="QB"),
        _player("Taylor", "3", rank=2, position="RB"),
        _player("Gibbs", "4", rank=3, position="RB"),
        _player("Chase", "5", rank=4, position="WR"),
        _player("Nacua", "6", rank=5, position="WR"),
        _player("Kelce", "7", rank=6, position="TE"),
    )
    slate = tier_best_available(
        players,
        settings=settings,
        roster=(_pick("Allen", "QB", "1"),),
    )
    assert [p.position for p in slate] == ["RB", "RB", "WR", "WR", "TE"]
    assert all(p.position != "QB" for p in slate)


def test_fallback_does_not_fill_the_slate_with_one_position(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    players = tuple(
        _player(f"QB{index}", str(index), rank=index, position="QB")
        for index in range(1, 6)
    ) + (
        _player("Taylor", "10", rank=10, position="RB"),
        _player("Chase", "11", rank=11, position="WR"),
    )
    slate = tier_best_available(players, settings=settings, roster=())
    assert [p.position for p in slate] == ["QB", "RB", "WR"]
    assert sum(1 for p in slate if p.position == "QB") == 1


def test_council_qb_stack_does_not_pad_a_second_qb(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    qbs = tuple(
        _player(name, str(index), rank=index, position="QB")
        for index, name in enumerate(
            ("Hurts", "Allen", "Jackson", "Mahomes", "Burrow"), start=1
        )
    )
    skill = (
        _player("Taylor", "10", rank=10, position="RB"),
        _player("Gibbs", "11", rank=11, position="RB"),
        _player("Chase", "12", rank=12, position="WR"),
        _player("Nacua", "13", rank=13, position="WR"),
        _player("Kelce", "14", rank=14, position="TE"),
    )
    fallback = tier_best_available(qbs + skill, settings=settings, roster=())
    assert fallback[0].name == "Hurts"
    chosen = qbs[1:] + (qbs[0],)
    items = _need_limited_items(chosen, fallback, settings, ())
    assert [item.name for item in items if item.position == "QB"] == ["Allen"]
    assert [item.position for item in items[:5]] == ["QB", "RB", "RB", "WR", "WR"]


def test_council_pool_drops_filled_qb(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    players = (
        _player("Hurts", "2", rank=1, position="QB"),
        _player("Taylor", "3", rank=2, position="RB"),
    )
    keys = council_pool_keys(players, settings, (_pick("Allen", "QB", "1"),))
    assert keys == ["yahoo:3"]

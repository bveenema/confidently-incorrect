from __future__ import annotations

import json
from pathlib import Path

import pytest

from data import DataConfigError
from data.__main__ import main
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck, load_pool_snapshot
from data.prerank import format_prerank, select_prerank


def _player(
    name: str,
    *,
    position: str = "QB",
    team: str = "BUF",
    value_rank: int | None,
    adp: float | None = None,
    fp_points: int | float | None = 100,
    scoring_incomplete: bool = False,
) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
        yahoo_id=None,
        fpid=None,
        tank_id=None,
        fp_points=fp_points,
        tank_points=None,
        source_delta=None,
        value_rank=value_rank,
        pos_rank=value_rank,
        adp=adp,
        adp_delta=None,
        tier=1,
        tier_break_after=False,
        scoring_incomplete=scoring_incomplete,
        join="fp_only",
    )


def _pool(*players: PooledPlayer) -> PlayerPool:
    return PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=players,
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )


def _snapshot(path: Path, pool: PlayerPool) -> Path:
    payload = {
        "schema_version": 1,
        "season": pool.season,
        "adp_scoring": pool.adp_scoring,
        "players": [
            {
                "name": p.name,
                "position": p.position,
                "team": p.team,
                "yahoo_id": p.yahoo_id,
                "fpid": p.fpid,
                "tank_id": p.tank_id,
                "fp_points": p.fp_points,
                "tank_points": p.tank_points,
                "source_delta": p.source_delta,
                "value_rank": p.value_rank,
                "pos_rank": p.pos_rank,
                "adp": p.adp,
                "adp_delta": p.adp_delta,
                "tier": p.tier,
                "tier_break_after": p.tier_break_after,
                "scoring_incomplete": p.scoring_incomplete,
                "join": p.join,
            }
            for p in pool.players
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_select_orders_by_value_rank_not_adp() -> None:
    pool = _pool(
        _player("Late ADP Star", value_rank=1, adp=40.0, fp_points=400),
        _player("Early ADP Role", value_rank=2, adp=2.0, fp_points=200),
        _player("Boot", position="K", team="NYJ", value_rank=None, scoring_incomplete=True),
    )
    rows = select_prerank(pool, limit=10)
    assert [p.name for p in rows] == ["Late ADP Star", "Early ADP Role"]
    assert all(p.position != "K" for p in rows)


def test_select_respects_limit() -> None:
    pool = _pool(
        _player("A", value_rank=1),
        _player("B", value_rank=2),
        _player("C", value_rank=3),
    )
    rows = select_prerank(pool, limit=2)
    assert [p.name for p in rows] == ["A", "B"]


def test_select_rejects_empty_and_bad_limit() -> None:
    empty = _pool(_player("Boot", position="K", team="NYJ", value_rank=None, scoring_incomplete=True))
    with pytest.raises(DataConfigError, match="no complete-scoring"):
        select_prerank(empty)
    pool = _pool(_player("A", value_rank=1))
    with pytest.raises(DataConfigError, match="limit"):
        select_prerank(pool, limit=0)


def test_format_is_numbered_and_says_not_adp() -> None:
    pool = _pool(
        _player("Late ADP Star", value_rank=1, adp=40.0),
        _player("Early ADP Role", value_rank=2, adp=2.0),
        _player("Boot", position="K", team="NYJ", value_rank=None, scoring_incomplete=True),
    )
    text = format_prerank(select_prerank(pool), pool)
    assert "not published ADP" in text
    assert "omitted_incomplete=1" in text
    assert "1\tLate ADP Star\tQB\tBUF" in text
    assert "2\tEarly ADP Role\tQB\tBUF" in text
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    assert "Boot" not in body
    assert "40.0" not in body
    assert "2.0" not in body


def test_cli_pool_stdout_and_out(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pool = _pool(
        _player("Late ADP Star", value_rank=1, adp=40.0),
        _player("Early ADP Role", value_rank=2, adp=2.0),
    )
    snap = _snapshot(tmp_path / "player-pool.json", pool)
    assert main(["pre-rank", "--pool", str(snap), "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "1\tLate ADP Star\tQB\tBUF" in out
    assert "Early ADP Role" not in out

    dest = tmp_path / "sheet.txt"
    assert main(["pre-rank", "--pool", str(snap), "--out", str(dest)]) == 0
    status = capsys.readouterr().out
    assert "ok: wrote" in status
    assert dest.read_text(encoding="utf-8").startswith("# Pre-rank sheet")
    assert "2\tEarly ADP Role\tQB\tBUF" in dest.read_text(encoding="utf-8")


def test_cli_uses_state_dir_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pool = _pool(_player("Alpha", value_rank=1))
    _snapshot(tmp_path / "player-pool.json", pool)
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["pre-rank"]) == 0
    assert "1\tAlpha\tQB\tBUF" in capsys.readouterr().out


def test_cli_missing_pool_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nope.json"
    assert main(["pre-rank", "--pool", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "missing" in err


def test_load_pool_snapshot_roundtrip(tmp_path: Path) -> None:
    pool = _pool(_player("Alpha", value_rank=1, adp=12.5))
    path = _snapshot(tmp_path / "player-pool.json", pool)
    loaded = load_pool_snapshot(path)
    assert loaded.players[0].name == "Alpha"
    assert loaded.players[0].value_rank == 1
    assert loaded.season == 2026

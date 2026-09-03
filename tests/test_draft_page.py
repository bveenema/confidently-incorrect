from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import unquote

import pytest
from tests.test_league_settings import _minimal, _write

from data.league_settings import load_league_settings, load_league_settings_file
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.__main__ import main
from draft.errors import DraftConfigError, DraftStateError
from draft.io import save_pool_snapshot
from draft.pool_load import load_draft_pool
from draft.server import DraftApp, handle_request, require_snake, start_server


def _player(name: str, yahoo_id: str, *, team: str = "BUF") -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position="QB",
        team=team,
        yahoo_id=yahoo_id,
        fpid=int(yahoo_id),
        tank_id=None,
        fp_points=50,
        tank_points=40,
        source_delta=10,
        value_rank=1,
        pos_rank=1,
        adp=12.0,
        adp_delta=11.0,
        tier=1,
        tier_break_after=False,
        scoring_incomplete=False,
        join="yahoo_id",
    )


def _snake_settings(tmp_path: Path, team_count: int = 8) -> Path:
    payload = _minimal(team_count)
    payload["draft"] = {"rounds": 3, "type": "snake"}
    return _write(tmp_path, payload)


def _app(tmp_path: Path, players: tuple[PooledPlayer, ...]) -> DraftApp:
    _snake_settings(tmp_path)
    pool = PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=players,
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )
    return DraftApp(tmp_path, pool)


def test_require_snake(tmp_path: Path) -> None:
    payload = _minimal(8)
    payload["draft"] = {"rounds": 15, "type": "auction"}
    settings = load_league_settings_file(_write(tmp_path, payload))
    with pytest.raises(DraftConfigError, match="not snake"):
        require_snake(settings)


def test_setup_pick_advance_undo(tmp_path: Path) -> None:
    alpha = _player("Alpha", "1")
    bravo = _player("Bravo", "2", team="KC")
    app = _app(tmp_path, (alpha, bravo))

    page = handle_request(app, "GET", "/", "", {})
    assert page.status == 200
    assert page.body is not None
    assert "Our draft slot" in page.body

    setup = handle_request(app, "POST", "/setup", "", {"our_slot": "8"})
    assert setup.status == 303
    assert setup.location is not None and "slot saved" in unquote(setup.location)

    recorded = handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    assert recorded.status == 303
    assert recorded.location is not None and "recorded Alpha" in unquote(
        recorded.location
    )

    board_page = handle_request(app, "GET", "/", "", {})
    assert board_page.body is not None
    assert "Next pick: 2" in board_page.body
    assert "Alpha" in board_page.body
    assert "Bravo" in board_page.body
    assert "Available (1)" in board_page.body

    advanced = handle_request(app, "POST", "/advance", "", {})
    assert advanced.status == 303
    undone = handle_request(app, "POST", "/undo", "", {})
    assert undone.status == 303


def test_page_hides_unnamed_on_our_pick(tmp_path: Path) -> None:
    app = _app(tmp_path, (_player("Alpha", "1"),))
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert "Other team picked" not in page.body
    with pytest.raises(DraftStateError, match="is ours"):
        handle_request(app, "POST", "/advance", "", {})


def test_ambiguous_pick_lists_candidates(tmp_path: Path) -> None:
    players = (
        _player("Josh Allen", "1", team="BUF"),
        _player("Josh Allen", "2", team="JAX"),
    )
    # second Allen as WR so names collide
    from dataclasses import replace

    players = (players[0], replace(players[1], position="WR"))
    app = _app(tmp_path, players)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    result = handle_request(app, "POST", "/pick", "", {"q": "Josh Allen"})
    assert result.status == 200
    assert result.body is not None
    assert "several matches" in result.body
    assert 'name="key"' in result.body
    chosen = handle_request(app, "POST", "/pick", "", {"key": "yahoo:2"})
    assert chosen.status == 303
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert "JAX" in page.body


def test_pick_already_drafted(tmp_path: Path) -> None:
    app = _app(tmp_path, (_player("Alpha", "1"),))
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    with pytest.raises(DraftConfigError, match="already drafted"):
        handle_request(app, "POST", "/pick", "", {"q": "Alpha"})


def test_unknown_player(tmp_path: Path) -> None:
    app = _app(tmp_path, (_player("Alpha", "1"),))
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    with pytest.raises(DraftConfigError, match="no pool match"):
        handle_request(app, "POST", "/pick", "", {"q": "nobody"})


def test_http_roundtrip(tmp_path: Path) -> None:
    app = _app(tmp_path, (_player("Alpha", "1"),))
    httpd = start_server(app, host="127.0.0.1", port=0)
    thread_port = httpd.server_address[1]
    import threading

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", thread_port, timeout=5)
        conn.request("GET", "/")
        got = conn.getresponse()
        body = got.read().decode("utf-8")
        assert got.status == 200
        assert "Our draft slot" in body
        conn.request(
            "POST",
            "/setup",
            body="our_slot=3",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        posted = conn.getresponse()
        posted.read()
        assert posted.status == 303
        assert "slot saved" in unquote(posted.getheader("Location", ""))
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_snapshot_used_without_live_apis(tmp_path: Path) -> None:
    _snake_settings(tmp_path, 8)
    player = _player("Alpha", "1")
    pool = PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=(player,),
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )
    save_pool_snapshot(tmp_path / "player-pool.json", pool)
    settings = load_league_settings(tmp_path)
    loaded = load_draft_pool(tmp_path, settings, season=2026)
    assert loaded.players[0].name == "Alpha"


def test_cli_rejects_non_localhost() -> None:
    assert main(["serve", "--host", "0.0.0.0"]) == 2


def test_cli_missing_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["serve"]) == 1

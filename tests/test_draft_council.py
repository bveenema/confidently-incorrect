from __future__ import annotations

import threading
from pathlib import Path

import pytest
from tests.test_league_settings import _minimal, _write

from council.errors import CouncilRunError
from council.ledger import (
    ConsideredOption,
    ensure_ledger,
    ensure_season,
    insert_considered_options,
    insert_decision,
    insert_run,
)
from council.orchestrator import CouncilResult
from council.schema import Brief, GmAction, GmDecision, Recommendation
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from db import connect
from draft.__main__ import main
from draft.errors import DraftConfigError
from draft.fallback import tier_best_available
from draft.packet import build_draft_packet, packet_hash
from draft.recompute import DraftRecompute, NullRecompute
from draft.rehearsal import rehearsal_root
from draft.server import DraftApp, handle_request


def _player(
    name: str,
    yahoo_id: str,
    *,
    rank: int,
    team: str = "BUF",
    position: str = "QB",
) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
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
        tier=1 if rank <= 3 else 2,
        tier_break_after=rank == 3,
        scoring_incomplete=False,
        join="yahoo_id",
    )


PLAYERS = tuple(
    _player(name, str(index + 1), rank=index + 1)
    for index, name in enumerate(
        ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")
    )
)


def _snake_settings(tmp_path: Path, team_count: int = 8) -> Path:
    payload = _minimal(team_count)
    payload["draft"] = {"rounds": 3, "type": "snake"}
    payload["roster_slots"] = [
        {"position": "QB", "count": 1},
        {"position": "RB", "count": 2},
        {"position": "WR", "count": 2},
        {"position": "W/R/T", "count": 1},
    ]
    return _write(tmp_path, payload)


def _pool() -> PlayerPool:
    return PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=PLAYERS,
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )


def _decision(keys: list[str] | None = None) -> GmDecision:
    chosen = keys or [f"yahoo:{i}" for i in range(1, 6)]
    return GmDecision(
        decision_type="draft",
        final_actions=tuple(
            GmAction(action="draft", player_key=key, slot=None) for key in chosen
        ),
        adopted_from=("brand",),
        overruled=(),
        override_reason=None,
        unanimous_override=False,
        rationale="Ranked slate.",
        voice_line="Take the board.",
    )


def _result(run_id: int, keys: list[str] | None = None) -> CouncilResult:
    chosen = keys or [f"yahoo:{i}" for i in range(1, 6)]
    brief = Brief(
        persona="brand",
        decision_type="draft",
        recommendations=tuple(
            Recommendation(
                action="draft",
                player_key=key,
                player_name=f"P{key}",
                slot=None,
                priority=index + 1,
            )
            for index, key in enumerate(chosen)
        ),
        confidence=0.5,
        reasoning="Board order.",
        dissent=None,
        voice_line="Him.",
    )
    return CouncilResult(
        run_id=run_id,
        decision_type="draft",
        briefs=(brief,),
        rejected=(),
        absent=(),
        decision=_decision(chosen),
        failure_mode=None,
    )


def _ok_runner(**kwargs: object) -> CouncilResult:
    root = Path(str(kwargs["state_dir"]))
    ensure_ledger(root)
    ensure_season(root, str(kwargs["season_id"]))
    run_id = insert_run(
        root,
        season_id=str(kwargs["season_id"]),
        decision_type="draft",
        packet_hash=str(kwargs["packet_hash"]),
    )
    insert_decision(root, run_id, _decision())
    return _result(run_id)


def _wire(app: DraftApp, runner=_ok_runner) -> DraftApp:
    app.recompute = DraftRecompute(app, runner=runner)
    return app


def _ready(tmp_path: Path, *, runner=_ok_runner, rehearsal: bool = False) -> DraftApp:
    _snake_settings(tmp_path)
    app = DraftApp(
        tmp_path,
        _pool(),
        rehearsal=rehearsal,
        season_id="2026",
        recompute=NullRecompute(),
    )
    return _wire(app, runner)


def test_rehearsal_rejects_live_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    with pytest.raises(DraftConfigError, match="live runtime root"):
        rehearsal_root(tmp_path)
    assert main(["serve", "--state-dir", str(tmp_path)]) == 2


def test_rehearsal_banner_and_writes_land_in_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "live"
    rehearsal = tmp_path / "rehearsal"
    live.mkdir()
    rehearsal.mkdir()
    monkeypatch.setenv("CI_STATE_DIR", str(live))
    app = _ready(rehearsal, rehearsal=True)
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert "REHEARSAL" in page.body
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    app.recompute.wait_idle()
    assert (rehearsal / "kb.db").is_file()
    assert not (live / "kb.db").exists()
    with connect(rehearsal) as conn:
        n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert n >= 1


def test_each_pick_writes_draft_run_with_new_packet_hash(tmp_path: Path) -> None:
    app = _ready(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    app.recompute.wait_idle()
    handle_request(app, "POST", "/pick", "", {"q": "Bravo"})
    app.recompute.wait_idle()
    with connect(tmp_path) as conn:
        rows = conn.execute(
            """
            SELECT packet_hash FROM runs
            WHERE decision_type = 'draft' AND packet_hash IS NOT NULL
            ORDER BY id
            """
        ).fetchall()
    hashes = [row[0] for row in rows]
    assert len(hashes) >= 2
    assert hashes[-1] != hashes[-2]


def test_in_flight_recompute_is_superseded(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow(**kwargs: object) -> CouncilResult:
        started.set()
        assert release.wait(timeout=2)
        calls.append(str(kwargs["packet_hash"]))
        return _ok_runner(**kwargs)

    app = _ready(tmp_path, runner=slow)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    assert started.wait(timeout=2)
    started.clear()
    first_hash = app.recompute.latest.packet_hash if app.recompute.latest else ""
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    assert started.wait(timeout=2)
    release.set()
    app.recompute.wait_idle()
    latest = app.recompute.latest
    assert latest is not None
    assert latest.packet_hash != first_hash
    assert latest.packet_hash in calls
    assert len(set(calls)) == 2


def test_pick_post_returns_while_model_is_in_flight(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow(**kwargs: object) -> CouncilResult:
        started.set()
        assert release.wait(timeout=2)
        return _ok_runner(**kwargs)

    app = _ready(tmp_path, runner=slow)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    started.wait(timeout=2)
    started.clear()
    posted = handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    assert posted.status == 303
    assert started.wait(timeout=2)
    assert not release.is_set()
    page = handle_request(app, "GET", "/", "", {})
    assert page.status == 200
    assert page.body is not None
    assert "Council slate" in page.body
    release.set()
    app.recompute.wait_idle()


def test_model_failure_falls_through_to_tiers(tmp_path: Path) -> None:
    def boom(**kwargs: object) -> CouncilResult:
        raise CouncilRunError("run failed: gm_missing", failure_mode="gm_missing")

    app = _ready(tmp_path, runner=boom)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    app.recompute.wait_idle()
    latest = app.recompute.latest
    assert latest is not None
    assert latest.source == "fallback"
    assert latest.failure_mode == "gm_missing"
    assert len(latest.items) >= 5
    got = {item.player_key for item in latest.items}
    assert "yahoo:1" not in got
    assert got == {f"yahoo:{i}" for i in range(2, 7)}
    with connect(tmp_path) as conn:
        modes = [
            row[0]
            for row in conn.execute(
                "SELECT failure_mode FROM runs WHERE decision_type = 'draft'"
            )
        ]
    assert "gm_missing" in modes


def test_considered_options_written_before_chosen(tmp_path: Path) -> None:
    app = _ready(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"q": "Alpha"})
    app.recompute.wait_idle()
    with connect(tmp_path) as conn:
        rows = conn.execute(
            "SELECT chosen FROM considered_options ORDER BY id"
        ).fetchall()
    assert rows
    assert all(row[0] == 0 for row in rows)


def test_insert_considered_options_rejects_chosen_flag(tmp_path: Path) -> None:
    ensure_ledger(tmp_path)
    ensure_season(tmp_path, "2026")
    run_id = insert_run(
        tmp_path, season_id="2026", decision_type="draft", packet_hash="abc"
    )
    with pytest.raises(Exception, match="before any chosen flag"):
        insert_considered_options(
            tmp_path,
            run_id,
            (
                ConsideredOption(
                    persona="maddox",
                    player_key="yahoo:1",
                    contemplated_action="draft",
                    chosen=1,
                ),
            ),
        )


def test_fallback_ranks_by_value_rank() -> None:
    slate = tier_best_available(PLAYERS)
    assert [p.name for p in slate] == [
        "Alpha",
        "Bravo",
        "Charlie",
        "Delta",
        "Echo",
    ]


def test_packet_hash_changes_when_a_pick_is_recorded(tmp_path: Path) -> None:
    from data.league_settings import load_league_settings
    from draft.board import new_board, record_player, set_our_slot

    _snake_settings(tmp_path)
    settings = load_league_settings(tmp_path)
    board = set_our_slot(new_board(settings.team_count, settings.draft.rounds), 1)
    first = build_draft_packet(board, settings, PLAYERS)
    board = record_player(board, PLAYERS[0])
    remaining = PLAYERS[1:]
    second = build_draft_packet(board, settings, remaining)
    assert packet_hash(first) != packet_hash(second)


def test_page_lists_five_after_setup(tmp_path: Path) -> None:
    app = _ready(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "8"})
    app.recompute.wait_idle()
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    for name in ("Alpha", "Bravo", "Charlie", "Delta", "Echo"):
        assert name in page.body

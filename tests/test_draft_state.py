from __future__ import annotations

import json
import threading
from pathlib import Path

from tests.test_league_settings import _minimal, _write

from council.ledger import (
    ensure_ledger,
    ensure_season,
    insert_brief_row,
    insert_decision,
    insert_run,
)
from council.orchestrator import CouncilResult
from council.schema import Brief, GmAction, GmDecision, Recommendation
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.notes import NullNotes
from draft.packet import build_draft_packet, packet_hash
from draft.recompute import DraftRecompute, NullRecompute
from draft.server import DraftApp, handle_request


def _player(name: str, yahoo_id: str, *, rank: int) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position="QB",
        team="BUF",
        yahoo_id=yahoo_id,
        fpid=int(yahoo_id),
        tank_id=None,
        fp_points=100 - rank,
        tank_points=90 - rank,
        source_delta=10,
        value_rank=rank,
        pos_rank=rank,
        adp=float(rank),
        adp_delta=0.0,
        tier=1,
        tier_break_after=False,
        scoring_incomplete=False,
        join="yahoo_id",
    )


PLAYERS = tuple(
    _player(name, str(index + 1), rank=index + 1)
    for index, name in enumerate(
        ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot")
    )
)


def _settings(tmp_path: Path, team_count: int = 2, rounds: int = 2) -> None:
    payload = _minimal(team_count)
    payload["draft"] = {"rounds": rounds, "type": "snake"}
    _write(tmp_path, payload)


def _pool() -> PlayerPool:
    return PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=PLAYERS,
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )


def _decision() -> GmDecision:
    return GmDecision(
        decision_type="draft",
        final_actions=tuple(
            GmAction(action="draft", player_key=f"yahoo:{i}", slot=None)
            for i in range(1, 6)
        ),
        adopted_from=("brand",),
        overruled=(),
        override_reason=None,
        unanimous_override=False,
        rationale="Ranked slate.",
        voice_line="Take the board.",
    )


def _result(run_id: int) -> CouncilResult:
    brief = Brief(
        persona="brand",
        decision_type="draft",
        recommendations=tuple(
            Recommendation(
                action="draft",
                player_key=f"yahoo:{i}",
                player_name=f"P{i}",
                slot=None,
                priority=i,
            )
            for i in range(1, 6)
        ),
        confidence=0.7,
        reasoning="Board order.",
        dissent="No.",
        voice_line="Him.",
    )
    return CouncilResult(
        run_id=run_id,
        decision_type="draft",
        briefs=(brief,),
        rejected=(),
        absent=(),
        decision=_decision(),
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


def _ready(tmp_path: Path, runner=_ok_runner) -> DraftApp:
    _settings(tmp_path)
    app = DraftApp(
        tmp_path,
        _pool(),
        season_id="2026",
        recompute=NullRecompute(),
        notes=NullNotes(),
    )
    app.recompute = DraftRecompute(app, runner=runner)
    return app


def _state(app: DraftApp, query: str = "") -> dict[str, object]:
    result = handle_request(app, "GET", "/state", query, {})
    assert result.status == 200
    assert result.content_type.startswith("application/json")
    assert result.body is not None
    payload = json.loads(result.body)
    assert isinstance(payload, dict)
    return payload


def test_state_setup_phase(tmp_path: Path) -> None:
    app = _ready(tmp_path)
    payload = _state(app)
    assert payload["phase"] == "setup"
    assert payload["on_the_clock"] is None
    assert payload["upcoming"] is None
    assert payload["slate"] is None
    assert payload["council_running"] is False


def test_state_held_worker_is_fallback_and_running(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow(**kwargs: object) -> CouncilResult:
        started.set()
        assert release.wait(timeout=2)
        return _ok_runner(**kwargs)

    app = _ready(tmp_path, runner=slow)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    assert started.wait(timeout=2)
    payload = _state(app)
    assert payload["phase"] == "drafting"
    assert payload["slate"] is not None
    slate = payload["slate"]
    assert isinstance(slate, dict)
    assert slate["source"] == "fallback"
    assert isinstance(slate["items"], list)
    assert slate["items"]
    assert payload["panel"] is None
    assert payload["council_running"] is True
    on_clock = payload["on_the_clock"]
    assert isinstance(on_clock, dict)
    assert on_clock["ours"] is True
    release.set()
    app.recompute.wait_idle()
    done = _state(app)
    assert done["council_running"] is False
    assert done["panel"] is not None
    panel = done["panel"]
    assert isinstance(panel, dict)
    assert panel["decision"]["rationale"] == "Ranked slate."
    assert panel["briefs"][0]["persona"] == "brand"
    assert panel["briefs"][0]["dissent"] == "No."


def test_state_drops_stale_panel_hash(tmp_path: Path) -> None:
    from draft.recompute import DraftSlate, SlateDecision, SlatePanel

    app = _ready(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    app.recompute.wait_idle()
    latest = app.recompute.latest
    assert latest is not None
    app.recompute.latest = DraftSlate(
        packet_hash=latest.packet_hash,
        items=latest.items,
        source="council",
        run_id=1,
        failure_mode=None,
        panel=SlatePanel(
            packet_hash="not-the-current-hash",
            briefs=(),
            decision=SlateDecision(
                rationale="stale",
                adopted_from=(),
                overruled=(),
                final_actions=(),
            ),
        ),
    )
    payload = _state(app)
    assert payload["panel"] is None
    assert payload["slate"] is not None


def test_recover_panel_from_kb_on_new_app(tmp_path: Path) -> None:
    first = _ready(tmp_path)
    handle_request(first, "POST", "/setup", "", {"our_slot": "1"})
    first.recompute.wait_idle()
    settings, board = first.load()
    digest = packet_hash(build_draft_packet(board, settings, first.pool.players))
    ensure_ledger(tmp_path)
    ensure_season(tmp_path, "2026")
    run_id = insert_run(
        tmp_path,
        season_id="2026",
        decision_type="draft",
        packet_hash=digest,
    )
    brief = Brief(
        persona="taco",
        decision_type="draft",
        recommendations=tuple(
            Recommendation(
                action="draft",
                player_key="yahoo:1",
                player_name="Alpha",
                slot=None,
                priority=1,
            )
            for _ in range(5)
        ),
        confidence=0.4,
        reasoning="Recovered.",
        dissent=None,
        voice_line="Go.",
    )
    insert_brief_row(
        tmp_path,
        run_id,
        persona="taco",
        brief=brief,
        model="test",
        tokens=1,
        cost=0.0,
    )
    insert_decision(tmp_path, run_id, _decision())

    second = DraftApp(
        tmp_path,
        _pool(),
        season_id="2026",
        recompute=NullRecompute(),
        notes=NullNotes(),
    )
    second.recompute = DraftRecompute(second, runner=_ok_runner)
    payload = _state(second)
    assert payload["panel"] is not None
    panel = payload["panel"]
    assert isinstance(panel, dict)
    assert panel["briefs"][0]["reasoning"] == "Recovered."
    assert second.recompute.latest is not None
    assert second.recompute.latest.panel is not None


def test_state_content_type_on_http(tmp_path: Path) -> None:
    from http.client import HTTPConnection

    app = _ready(tmp_path)
    from draft.server import start_server

    httpd = start_server(app, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/state")
        got = conn.getresponse()
        body = got.read().decode("utf-8")
        assert got.status == 200
        assert "application/json" in got.getheader("Content-Type", "")
        payload = json.loads(body)
        assert payload["phase"] == "setup"
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()

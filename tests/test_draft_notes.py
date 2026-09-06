from __future__ import annotations

from pathlib import Path

from tests.test_league_settings import _minimal, _write

from data.league_settings import load_league_settings
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.board import new_board, set_our_slot
from draft.notes import NullNotes
from draft.packet import build_draft_packet, packet_hash
from draft.recompute import DraftSlate, NullRecompute, SlateItem
from draft.server import DraftApp, handle_request
from notes.append import MAX_DRAFT_PICK_NOTES, append_note, list_notes, load_notes_text


def _player(name: str, yahoo_id: str, *, rank: int = 1) -> PooledPlayer:
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


def _settings(tmp_path: Path, *, team_count: int = 2, rounds: int = 2) -> Path:
    payload = _minimal(team_count)
    payload["draft"] = {"rounds": rounds, "type": "snake"}
    return _write(tmp_path, payload)


def _pool() -> PlayerPool:
    return PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=PLAYERS,
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )


def _lasso(mode: str, packet: dict[str, object]) -> str:
    return f"{mode} note for slot {packet.get('our_slot')}"


def _app(tmp_path: Path, **kwargs: object) -> DraftApp:
    _settings(tmp_path)
    return DraftApp(
        tmp_path,
        _pool(),
        season_id="2026",
        recompute=kwargs.get("recompute", NullRecompute()),  # type: ignore[arg-type]
        lasso=kwargs.get("lasso", _lasso),  # type: ignore[arg-type]
        notes=kwargs.get("notes"),  # type: ignore[arg-type]
    )


def test_lasso_open_and_close_and_one_note_per_our_pick(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "2"})
    app.notes.wait_idle()
    events = [note.event for note in list_notes(tmp_path)]
    assert events == ["draft-open"]
    assert list_notes(tmp_path)[0].persona == "lasso"
    assert list_notes(tmp_path)[0].season_id == "2026"

    handle_request(app, "POST", "/advance", "", {})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:2"})
    app.notes.wait_idle()

    notes = list_notes(tmp_path)
    events = [note.event for note in notes]
    assert events.count("draft-open") == 1
    assert events.count("draft-pick") == 2
    assert events.count("draft-close") == 0
    assert all(note.persona == "maddox" for note in notes if note.event == "draft-pick")
    assert "[[Alpha]]" in notes[1].body

    handle_request(app, "POST", "/advance", "", {})
    app.notes.wait_idle()
    events = [note.event for note in list_notes(tmp_path)]
    assert events.count("draft-close") == 1
    assert list_notes(tmp_path)[-1].persona == "lasso"
    assert events.count("draft-pick") == 2


def test_other_picks_and_recompute_do_not_append(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "2"})
    app.notes.wait_idle()
    handle_request(app, "POST", "/advance", "", {})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    app.notes.wait_idle()
    before = list_notes(tmp_path)
    assert [note.event for note in before] == ["draft-open", "draft-pick"]

    app.persist(app.load()[1])
    app.notes.wait_idle()
    assert list_notes(tmp_path) == before


def test_undo_retracts_our_pick_note(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    app.notes.wait_idle()
    assert any(note.event == "draft-pick" for note in list_notes(tmp_path))

    handle_request(app, "POST", "/undo", "", {})
    app.notes.wait_idle()
    assert not any(note.event == "draft-pick" for note in list_notes(tmp_path))
    assert any(note.event == "draft-open" for note in list_notes(tmp_path))


def test_our_last_pick_writes_pick_and_close(tmp_path: Path) -> None:
    _settings(tmp_path, team_count=2, rounds=1)
    app = DraftApp(
        tmp_path,
        _pool(),
        season_id="2026",
        recompute=NullRecompute(),
        lasso=_lasso,
    )
    handle_request(app, "POST", "/setup", "", {"our_slot": "2"})
    handle_request(app, "POST", "/advance", "", {})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    app.notes.wait_idle()
    events = [note.event for note in list_notes(tmp_path)]
    assert events == ["draft-open", "draft-pick", "draft-close"]


def test_lasso_failure_does_not_block_setup(tmp_path: Path) -> None:
    def boom(_mode: str, _packet: dict[str, object]) -> str:
        raise RuntimeError("no color")

    app = _app(tmp_path, lasso=boom)
    result = handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    app.notes.wait_idle()
    assert result.status == 303
    assert list_notes(tmp_path) == []


def test_null_notes_writes_nothing(tmp_path: Path) -> None:
    app = _app(tmp_path, notes=NullNotes())
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    assert list_notes(tmp_path) == []


def test_packet_includes_notes_and_stays_small(tmp_path: Path) -> None:
    _settings(tmp_path)
    settings = load_league_settings(tmp_path)
    board = set_our_slot(new_board(settings.team_count, settings.draft.rounds), 1)
    empty = build_draft_packet(board, settings, PLAYERS)
    assert "notes" not in empty

    append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-open",
        body="Open.",
    )
    for overall in range(1, MAX_DRAFT_PICK_NOTES + 1):
        append_note(
            tmp_path,
            persona="maddox",
            season_id="2026",
            event="draft-pick",
            overall=overall,
            body=f"Took [[P{overall}]] at overall {overall}.",
        )
    append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-close",
        body="Close.",
    )
    blob = load_notes_text(tmp_path)
    filled = build_draft_packet(board, settings, PLAYERS, notes=blob)
    assert "Open." in filled["notes"]
    assert "Close." in filled["notes"]
    assert len(filled["notes"]) < 12_000
    assert packet_hash(empty) != packet_hash(filled)
    assert tmp_path in (tmp_path / "notes").parents


def test_pick_body_uses_captured_slate(tmp_path: Path) -> None:
    slate = DraftSlate(
        packet_hash="x",
        items=(
            SlateItem(1, "yahoo:3", "Charlie", "QB", "BUF"),
            SlateItem(2, "yahoo:1", "Alpha", "QB", "BUF"),
        ),
        source="fallback",
        run_id=None,
        failure_mode=None,
    )
    recompute = NullRecompute()
    recompute.latest = slate
    app = DraftApp(
        tmp_path,
        _pool(),
        season_id="2026",
        recompute=recompute,
        lasso=_lasso,
    )
    _settings(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    pick = next(note for note in list_notes(tmp_path) if note.event == "draft-pick")
    assert "Slate rank 2" in pick.body


def test_recompute_schedule_does_not_append_notes(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    handle_request(app, "POST", "/pick", "", {"key": "yahoo:1"})
    app.notes.wait_idle()
    before = [note.event for note in list_notes(tmp_path)]
    app.persist(app.load()[1])
    app.notes.wait_idle()
    assert [note.event for note in list_notes(tmp_path)] == before

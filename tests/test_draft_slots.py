from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

import pytest
from tests.test_league_settings import _minimal, _write

from data.league_settings import load_league_settings
from data.pool import PlayerPool, PooledPlayer, QbInflationCheck
from draft.board import new_board, set_our_slot
from draft.io import load_board
from draft.notes import NullNotes
from draft.packet import build_draft_packet
from draft.recompute import NullRecompute
from draft.server import DraftApp, handle_request
from draft.slots import (
    display_for,
    load_slots,
    merge_form,
    pseudonym_for,
    save_slots,
)
from notes.append import list_notes

DISPLAY = "UNIQUE_GOATS_XYZ"


def _player(name: str, yahoo_id: str) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position="QB",
        team="BUF",
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


def _settings(tmp_path: Path, team_count: int = 2, rounds: int = 2) -> None:
    payload = _minimal(team_count)
    payload["draft"] = {"rounds": rounds, "type": "snake"}
    _write(tmp_path, payload)


def _app(tmp_path: Path) -> DraftApp:
    _settings(tmp_path)
    pool = PlayerPool(
        season=2026,
        adp_scoring="PPR",
        players=(_player("Alpha", "1"), _player("Bravo", "2")),
        qb_inflation=QbInflationCheck(True, None, (), "test"),
    )
    return DraftApp(tmp_path, pool, recompute=NullRecompute(), notes=NullNotes())


def test_missing_file_is_empty_map(tmp_path: Path) -> None:
    mapping = load_slots(tmp_path)
    assert mapping.slots == {}
    assert display_for(mapping, 3) == "Slot 3"
    assert pseudonym_for(mapping, 3) == "slot-3"


def test_roundtrip_and_display_modes(tmp_path: Path) -> None:
    from draft.slots import SlotLabel, SlotMap

    save_slots(
        tmp_path,
        SlotMap(slots={1: SlotLabel(pseudonym="slot-1", display=DISPLAY)}),
    )
    loaded = load_slots(tmp_path)
    assert display_for(loaded, 1) == DISPLAY
    assert display_for(loaded, 1, names="pseudonym") == "slot-1"
    identities = (tmp_path / "identities.json").read_text(encoding="utf-8")
    order = (tmp_path / "draft-slots.json").read_text(encoding="utf-8")
    assert "UNIQUE_GOATS" in identities
    assert "UNIQUE_GOATS" not in order
    assert '"1": "m1"' in order or '"1":"m1"' in order.replace(" ", "")


def test_merge_form_empty_unseats_but_keeps_member(tmp_path: Path) -> None:
    from draft.slots import SlotLabel, SlotMap

    existing = SlotMap(
        slots={1: SlotLabel(pseudonym="manager-1", display=DISPLAY, member_id="m1")}
    )
    save_slots(tmp_path, existing)
    seated = load_slots(tmp_path)
    cleared = merge_form(seated, {"display_1": ""}, team_count=2)
    assert 1 not in cleared.slots
    assert "m1" in cleared.identities.members
    assert cleared.identities.members["m1"].display == DISPLAY


def test_display_names_never_enter_packet_board_or_notes(tmp_path: Path) -> None:
    _settings(tmp_path)
    app = _app(tmp_path)
    handle_request(
        app,
        "POST",
        "/setup",
        "",
        {"our_slot": "2", "display_1": DISPLAY, "display_2": "US_TEAM_ABC"},
    )
    settings = load_league_settings(tmp_path)
    board = load_board(tmp_path, settings.team_count, settings.draft.rounds)
    packet = build_draft_packet(board, settings, app.pool.players)
    blob = json.dumps(packet)
    assert DISPLAY not in blob
    assert "US_TEAM_ABC" not in blob
    board_text = (tmp_path / "draft-board.json").read_text(encoding="utf-8")
    assert DISPLAY not in board_text
    assert "US_TEAM_ABC" not in board_text

    notes_app = DraftApp(
        tmp_path,
        app.pool,
        recompute=NullRecompute(),
    )
    handle_request(notes_app, "POST", "/advance", "", {})
    handle_request(notes_app, "POST", "/pick", "", {"key": "yahoo:1"})
    pick = next(note for note in list_notes(tmp_path) if note.event == "draft-pick")
    assert DISPLAY not in pick.body
    assert "US_TEAM_ABC" not in pick.body
    assert "Seat manager-2" in pick.body
    assert "Previous clock manager-1" in pick.body
    order = (tmp_path / "draft-slots.json").read_text(encoding="utf-8")
    assert DISPLAY not in order
    assert "US_TEAM_ABC" not in order


def test_labels_route_and_page_shows_display(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    saved = handle_request(
        app, "POST", "/labels", "", {"display_1": DISPLAY, "display_2": "Other"}
    )
    assert saved.status == 303
    assert saved.location is not None and "labels saved" in unquote(saved.location)
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert DISPLAY in page.body
    hidden = handle_request(app, "GET", "/", "names=pseudonym", {})
    assert hidden.body is not None
    assert DISPLAY not in hidden.body
    assert "manager-1" in hidden.body


def test_page_uses_slot_fallback_without_map(tmp_path: Path) -> None:
    app = _app(tmp_path)
    handle_request(app, "POST", "/setup", "", {"our_slot": "1"})
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert "Slot 1" in page.body


def test_legacy_object_slots_file_fails_loud(tmp_path: Path) -> None:
    (tmp_path / "draft-slots.json").write_text(
        '{"schema_version": 1, "slots": {"1": {"display": "x"}}}',
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="identities.json"):
        load_slots(tmp_path)


def test_invalid_slots_file_fails_loud(tmp_path: Path) -> None:
    (tmp_path / "draft-slots.json").write_text("{", encoding="utf-8")
    with pytest.raises(Exception, match="invalid JSON"):
        load_slots(tmp_path)


def test_set_our_slot_still_refuses_after_picks(tmp_path: Path) -> None:
    board = set_our_slot(new_board(2, 2), 1)
    from draft.board import record_player

    board = record_player(board, _player("Alpha", "1"))
    with pytest.raises(Exception, match="cannot change"):
        set_our_slot(board, 2)


def _write_room(tmp_path: Path, *, ours_id: str = "m2") -> None:
    from draft.identities import Identities, Member, save_identities
    from draft.slots import save_order

    save_identities(
        tmp_path,
        Identities(
            members={
                "m1": Member("m1", "Red Zone", "Other Team"),
                "m2": Member("m2", "Hail Mary", "Us Team", ours=True),
            }
        ),
    )
    save_order(tmp_path, {1: "m1", 2: ours_id})


def test_get_derives_our_slot_from_ours_flag(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _write_room(tmp_path)
    page = handle_request(app, "GET", "/", "", {})
    assert page.status == 200
    assert page.body is not None
    assert "Our draft slot" not in page.body
    assert "Us Team" in page.body
    board = load_board(tmp_path, 2, 2)
    assert board.our_slot == 2


def test_order_post_moves_us_to_slot_one(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _write_room(tmp_path)
    handle_request(app, "GET", "/", "", {})
    moved = handle_request(
        app, "POST", "/order", "", {"member_1": "m2", "member_2": "m1"}
    )
    assert moved.status == 303
    board = load_board(tmp_path, 2, 2)
    assert board.our_slot == 1
    mapping = load_slots(tmp_path)
    assert mapping.label(1) is not None
    assert mapping.label(1).member_id == "m2"
    page = handle_request(app, "GET", "/", "", {})
    assert page.body is not None
    assert 'data-ours="true"' in page.body
    assert 'name="member_1" value="m2"' in page.body


def test_order_refuses_after_picks(tmp_path: Path) -> None:
    from draft.board import record_player
    from draft.io import save_board

    app = _app(tmp_path)
    _write_room(tmp_path)
    handle_request(app, "GET", "/", "", {})
    board = load_board(tmp_path, 2, 2)
    save_board(tmp_path, record_player(board, _player("Alpha", "1")))
    with pytest.raises(Exception, match="cannot reorder"):
        handle_request(
            app, "POST", "/order", "", {"member_1": "m2", "member_2": "m1"}
        )


def test_display_name_fallback_finds_our_team(tmp_path: Path) -> None:
    from draft.identities import OUR_TEAM_DISPLAY, Identities, Member, save_identities
    from draft.slots import save_order

    app = _app(tmp_path)
    save_identities(
        tmp_path,
        Identities(
            members={
                "m1": Member("m1", "Red Zone", "Other Team"),
                "m2": Member("m2", "Hail Mary", OUR_TEAM_DISPLAY),
            }
        ),
    )
    save_order(tmp_path, {1: "m1", 2: "m2"})
    handle_request(app, "GET", "/", "", {})
    assert load_board(tmp_path, 2, 2).our_slot == 2

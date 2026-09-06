from __future__ import annotations

from pathlib import Path

import pytest

from notes.append import (
    MAX_DRAFT_PICK_NOTES,
    append_note,
    draft_notes_path,
    list_notes,
    load_notes_text,
    retract_note,
)
from notes.errors import NotesError


def _pick(root: Path, overall: int, name: str = "Alpha") -> None:
    append_note(
        root,
        persona="maddox",
        season_id="2026",
        event="draft-pick",
        overall=overall,
        player_key=f"yahoo:{overall}",
        body=f"Took [[{name}]] at overall {overall}.",
    )


def test_append_stamps_persona_season_and_timestamp(tmp_path: Path) -> None:
    note = append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-open",
        body="Believe.",
        date="2026-09-06T20:00:00-04:00",
    )
    assert note is not None
    assert note.persona == "lasso"
    assert note.season_id == "2026"
    assert note.date == "2026-09-06T20:00:00-04:00"
    assert note.entity_type == "draft"
    assert note.week == "draft"
    text = draft_notes_path(tmp_path).read_text(encoding="utf-8")
    assert "persona: lasso" in text
    assert "season_id: 2026" in text
    assert "event: draft-open" in text
    assert "Believe." in text


def test_append_is_idempotent_for_open_and_same_overall(tmp_path: Path) -> None:
    first = append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-open",
        body="First.",
    )
    second = append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-open",
        body="Second.",
    )
    assert first is not None
    assert second is None
    _pick(tmp_path, 3)
    assert (
        append_note(
            tmp_path,
            persona="maddox",
            season_id="2026",
            event="draft-pick",
            overall=3,
            body="Duplicate pick.",
        )
        is None
    )
    notes = list_notes(tmp_path)
    assert [note.event for note in notes] == ["draft-open", "draft-pick"]
    assert notes[0].body == "First."


def test_pick_cap_is_packet_guard(tmp_path: Path) -> None:
    for overall in range(1, MAX_DRAFT_PICK_NOTES + 1):
        _pick(tmp_path, overall)
    assert (
        append_note(
            tmp_path,
            persona="maddox",
            season_id="2026",
            event="draft-pick",
            overall=99,
            body="Too many.",
        )
        is None
    )
    assert len([n for n in list_notes(tmp_path) if n.event == "draft-pick"]) == 15
    close = append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-close",
        body="That's the draft.",
    )
    assert close is not None


def test_retract_pick_and_close(tmp_path: Path) -> None:
    _pick(tmp_path, 1)
    append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-close",
        body="Done.",
    )
    assert retract_note(tmp_path, event="draft-pick", overall=1) is True
    assert retract_note(tmp_path, event="draft-close") is True
    assert list_notes(tmp_path) == []
    assert retract_note(tmp_path, event="draft-close") is False


def test_load_notes_skips_managers_and_uses_temp_dir_only(tmp_path: Path) -> None:
    append_note(
        tmp_path,
        persona="lasso",
        season_id="2026",
        event="draft-open",
        body="Open.",
    )
    managers = tmp_path / "notes" / "managers"
    managers.mkdir()
    (managers / "slot-3.md").write_text(
        "real name leak should not enter the packet\n",
        encoding="utf-8",
    )
    blob = load_notes_text(tmp_path)
    assert "Open." in blob
    assert "real name leak" not in blob
    assert tmp_path in draft_notes_path(tmp_path).parents


def test_rejects_unknown_persona_and_empty_body(tmp_path: Path) -> None:
    with pytest.raises(NotesError, match="unknown persona"):
        append_note(
            tmp_path,
            persona="commissioner",
            season_id="2026",
            event="draft-open",
            body="Hi.",
        )
    with pytest.raises(NotesError, match="empty"):
        append_note(
            tmp_path,
            persona="lasso",
            season_id="2026",
            event="draft-open",
            body="   ",
        )

"""Structured append tool for notes/. Timestamp and persona are tool-owned."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from council.schema import PERSONAS
from notes.errors import NotesError, NotesStateError

ET = ZoneInfo("America/New_York")
DRAFT_NOTES_FILE = "draft.md"
MANAGERS_DIR = "managers"
# Packet-size guard, not a league-derived rounds value (D-95 / D-102).
MAX_DRAFT_PICK_NOTES = 15
DRAFT_EVENTS = frozenset({"draft-open", "draft-pick", "draft-close"})
_ENTRY = re.compile(
    r"(?ms)^---\n(?P<front>.*?)\n---\n?(?P<body>.*?)(?=^---\n|\Z)"
)


@dataclass(frozen=True)
class Note:
    date: str
    persona: str
    season_id: str
    entity_type: str
    event: str
    week: str
    body: str
    overall: int | None = None
    player_key: str | None = None


def now_et() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def draft_notes_path(root: Path) -> Path:
    return root / "notes" / DRAFT_NOTES_FILE


def append_note(
    root: Path,
    *,
    persona: str,
    season_id: str,
    body: str,
    event: str,
    entity_type: str = "draft",
    week: str = "draft",
    overall: int | None = None,
    player_key: str | None = None,
    date: str | None = None,
) -> Note | None:
    """Append one attributed note. Idempotent on (event, overall).

    Returns None when the event is already recorded or the pick cap is hit.
    A failed write raises — this is a write path.
    """
    handle = persona.strip().lower()
    if handle not in PERSONAS:
        raise NotesError(f"unknown persona {persona!r}")
    if event not in DRAFT_EVENTS:
        raise NotesError(f"unknown notes event {event!r}")
    text = body.strip()
    if not text:
        raise NotesError("note body is empty")
    if event == "draft-pick" and overall is None:
        raise NotesError("draft-pick notes require overall")

    existing = list_notes(root)
    if _already_written(existing, event, overall):
        return None
    if event == "draft-pick" and _pick_count(existing) >= MAX_DRAFT_PICK_NOTES:
        return None

    note = Note(
        date=date or now_et(),
        persona=handle,
        season_id=str(season_id),
        entity_type=entity_type,
        event=event,
        week=week,
        body=text,
        overall=overall,
        player_key=player_key,
    )
    path = draft_notes_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = _read(path)
    if blob and not blob.endswith("\n"):
        blob += "\n"
    if blob and not blob.endswith("\n\n"):
        blob += "\n"
    _atomic_write(path, blob + render_note(note))
    return note


def retract_note(root: Path, *, event: str, overall: int | None = None) -> bool:
    """Remove the matching note. Used after undo. Raises on write failure."""
    path = draft_notes_path(root)
    notes = list_notes(root)
    kept = [note for note in notes if not _same_event(note, event, overall)]
    if len(kept) == len(notes):
        return False
    if not kept:
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise NotesStateError(f"failed deleting {path}: {exc}") from exc
        return True
    _atomic_write(path, "".join(render_note(note) for note in kept))
    return True


def list_notes(root: Path) -> list[Note]:
    path = draft_notes_path(root)
    if not path.is_file():
        return []
    return parse_notes(_read(path))


def load_notes_text(root: Path) -> str:
    """Wholesale notes blob for packets. Never includes notes/managers/."""
    vault = root / "notes"
    if not vault.is_dir():
        return ""
    parts: list[str] = []
    for path in sorted(vault.glob("*.md")):
        if path.parent.name == MANAGERS_DIR:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def parse_notes(text: str) -> list[Note]:
    notes: list[Note] = []
    for match in _ENTRY.finditer(text):
        meta = _parse_front(match.group("front"))
        overall_raw = meta.get("overall")
        overall = int(overall_raw) if overall_raw not in (None, "") else None
        player_key = meta.get("player_key") or None
        notes.append(
            Note(
                date=meta.get("date", ""),
                persona=meta.get("persona", ""),
                season_id=meta.get("season_id", ""),
                entity_type=meta.get("entity_type", ""),
                event=meta.get("event", ""),
                week=meta.get("week", ""),
                body=match.group("body").strip(),
                overall=overall,
                player_key=player_key,
            )
        )
    return notes


def render_note(note: Note) -> str:
    lines = [
        "---",
        f"date: {note.date}",
        f"persona: {note.persona}",
        f"season_id: {note.season_id}",
        f"entity_type: {note.entity_type}",
        f"event: {note.event}",
        f"week: {note.week}",
    ]
    if note.overall is not None:
        lines.append(f"overall: {note.overall}")
    if note.player_key:
        lines.append(f"player_key: {note.player_key}")
    lines.append("---")
    lines.append("")
    lines.append(note.body)
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def _already_written(notes: list[Note], event: str, overall: int | None) -> bool:
    return any(_same_event(note, event, overall) for note in notes)


def _same_event(note: Note, event: str, overall: int | None) -> bool:
    if note.event != event:
        return False
    if event == "draft-pick":
        return note.overall == overall
    return True


def _pick_count(notes: list[Note]) -> int:
    return sum(1 for note in notes if note.event == "draft-pick")


def _parse_front(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            continue
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotesStateError(f"failed reading {path}: {exc}") from exc


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise NotesStateError(f"failed writing {path}: {exc}") from exc

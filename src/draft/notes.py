"""Draft-night notes hooks. Recomputes never call this module (D-95)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from typing import Any

from council.credentials import model_for
from council.errors import CouncilError
from council.openrouter import OpenRouterClient
from council.prompts import LASSO_OUTPUT_CAP, lasso_system
from draft.board import DraftBoard, RecordedPick
from draft.errors import DraftStateError
from draft.packet import build_draft_packet, load_draft_strategy
from notes.append import append_note, load_notes_text, retract_note
from notes.errors import NotesError

LassoFn = Callable[[str, dict[str, Any]], str]


class NullNotes:
    """No vault writes. Used by pick-entry tests that are not issue 49."""

    def after_setup(self, board: DraftBoard) -> None:
        return None

    def after_our_pick(
        self, board: DraftBoard, pick: RecordedPick, slate: Any | None
    ) -> None:
        return None

    def after_complete(self, board: DraftBoard) -> None:
        return None

    def after_undo(self, board: DraftBoard, undone: RecordedPick | None) -> None:
        return None

    def wait_idle(self, timeout: float = 5.0) -> None:
        return None


class DraftNotes:
    def __init__(self, app: Any, *, lasso: LassoFn | None = None) -> None:
        self._app = app
        self._lasso = lasso
        self._lock = threading.Lock()
        self._generation = 0
        self._threads: list[threading.Thread] = []

    def after_setup(self, board: DraftBoard) -> None:
        self._start_lasso("draft-open", board)

    def after_our_pick(
        self, board: DraftBoard, pick: RecordedPick, slate: Any | None
    ) -> None:
        try:
            with self._lock:
                append_note(
                    self._app.root,
                    persona="maddox",
                    season_id=self._app.season_id,
                    event="draft-pick",
                    overall=pick.overall,
                    player_key=pick.player_key,
                    body=_pick_body(pick, slate),
                )
        except NotesError as exc:
            raise DraftStateError(str(exc)) from exc

    def after_complete(self, board: DraftBoard) -> None:
        if not board.complete:
            return
        with self._lock:
            self._generation += 1
            gen = self._generation
        self._start_lasso("draft-close", board, gen)

    def after_undo(self, board: DraftBoard, undone: RecordedPick | None) -> None:
        try:
            with self._lock:
                self._generation += 1
                if undone is not None and undone.ours and undone.kind == "player":
                    retract_note(
                        self._app.root, event="draft-pick", overall=undone.overall
                    )
                if not board.complete:
                    retract_note(self._app.root, event="draft-close")
        except NotesError as exc:
            raise DraftStateError(str(exc)) from exc

    def wait_idle(self, timeout: float = 5.0) -> None:
        for thread in list(self._threads):
            thread.join(timeout)

    def _start_lasso(
        self, event: str, board: DraftBoard, gen: int | None = None
    ) -> None:
        mode = "DRAFT_OPEN" if event == "draft-open" else "DRAFT_CLOSE"
        thread = threading.Thread(
            target=self._lasso_worker,
            args=(event, mode, board, gen),
            daemon=True,
            name=f"draft-lasso-{event}",
        )
        self._threads.append(thread)
        thread.start()

    def _lasso_worker(
        self, event: str, mode: str, board: DraftBoard, gen: int | None
    ) -> None:
        try:
            packet = self._packet(board)
            text = self._run_lasso(mode, packet)
        except Exception:
            return
        if not text:
            return
        try:
            with self._lock:
                if event == "draft-close" and gen != self._generation:
                    return
                append_note(
                    self._app.root,
                    persona="lasso",
                    season_id=self._app.season_id,
                    event=event,
                    body=text,
                )
        except NotesError as exc:
            raise DraftStateError(str(exc)) from exc

    def _run_lasso(self, mode: str, packet: dict[str, Any]) -> str:
        if self._lasso is not None:
            return _clip(_plain(self._lasso(mode, packet)))
        client = OpenRouterClient(self._app.root)
        try:
            completion = client.complete(
                model=model_for("lasso", client.credentials),
                system=lasso_system(_team_count(packet)),
                user=_lasso_user(mode, packet),
            )
        except CouncilError:
            return ""
        finally:
            client.close()
        return _clip(_plain(completion.content))

    def _packet(self, board: DraftBoard) -> dict[str, Any]:
        settings = self._app.settings()
        available = board.available(self._app.pool.players)
        return build_draft_packet(
            board,
            settings,
            available,
            draft_strategy=load_draft_strategy(self._app.root),
            notes=load_notes_text(self._app.root) or None,
        )


def _pick_body(pick: RecordedPick, slate: Any | None) -> str:
    name = pick.name or "Unknown"
    line = f"Took [[{name}]]"
    extra = [part for part in (pick.position, pick.team) if part]
    if extra:
        line += f" ({', '.join(extra)})"
    line += f" at overall {pick.overall}."
    lines = [line]
    items = getattr(slate, "items", None)
    if items:
        top = ", ".join(f"[[{item.name}]]" for item in items[:3])
        lines.append(f"On-page slate: {top}.")
        keys = [item.player_key for item in items]
        if pick.player_key and pick.player_key == keys[0]:
            lines.append("Took the top of the slate.")
        elif pick.player_key in keys:
            lines.append(f"Slate rank {keys.index(pick.player_key) + 1}.")
        else:
            lines.append("Off the displayed slate.")
    return "\n".join(lines)


def _lasso_user(mode: str, packet: Mapping[str, Any]) -> str:
    return (
        f"MODE: {mode}\n\n"
        f"DECISION PACKET\n{json.dumps(dict(packet), indent=2, sort_keys=True)}\n\n"
        "Write 2-4 sentences. Plain text only. No JSON. No picks."
    )


def _team_count(packet: Mapping[str, Any]) -> int | None:
    raw = packet.get("team_count")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return None
    return raw


def _plain(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    return stripped


def _clip(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= LASSO_OUTPUT_CAP:
        return cleaned
    return cleaned[:LASSO_OUTPUT_CAP].rstrip()

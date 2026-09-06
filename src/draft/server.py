"""Localhost HTTP handler for draft-board pick entry. No Yahoo, no FastAPI."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from data.errors import DataError
from data.league_settings import LeagueSettings, load_league_settings
from data.pool import PlayerPool
from draft.board import (
    DraftBoard,
    advance_unnamed,
    record_player,
    set_our_slot,
    undo_last,
)
from draft.errors import DraftConfigError, DraftError, DraftStateError
from draft.io import load_board, save_board
from draft.match import find_by_key, match_players
from draft.notes import DraftNotes, NullNotes
from draft.page import redirect_to, render_page
from draft.recompute import DraftRecompute, NullRecompute
from draft.slots import (
    apply_order,
    load_slots,
    merge_form,
    order_from_form,
    our_slot_from,
    save_order,
    save_slots,
)
from draft.state import build_state, names_mode


@dataclass(frozen=True)
class _Result:
    status: int
    location: str | None = None
    body: str | None = None
    content_type: str = "text/html; charset=utf-8"


def require_snake(settings: LeagueSettings) -> None:
    if settings.draft.type.strip().lower() != "snake":
        raise DraftConfigError(
            f"draft.type {settings.draft.type!r} is not snake. "
            "Set draft.type to snake in $CI_STATE_DIR/league-settings.json."
        )


class DraftApp:
    def __init__(
        self,
        root: Path,
        pool: PlayerPool,
        *,
        rehearsal: bool = False,
        season_id: str = "2026",
        recompute: DraftRecompute | NullRecompute | None = None,
        notes: DraftNotes | NullNotes | None = None,
        lasso: Any | None = None,
    ) -> None:
        self.root = root
        self.pool = pool
        self.rehearsal = rehearsal
        self.season_id = season_id
        self.lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self.generation = 0
        self._recovered = False
        self.recompute: DraftRecompute | NullRecompute = (
            recompute if recompute is not None else DraftRecompute(self)
        )
        self.notes: DraftNotes | NullNotes = (
            notes if notes is not None else DraftNotes(self, lasso=lasso)
        )

    def bump(self) -> None:
        with self._gen_lock:
            self.generation += 1

    def settings(self) -> LeagueSettings:
        settings = load_league_settings(self.root)
        require_snake(settings)
        return settings

    def load(self) -> tuple[LeagueSettings, DraftBoard]:
        settings = self.settings()
        board = load_board(self.root, settings.team_count, settings.draft.rounds)
        if not self._recovered:
            self._recovered = True
            self.recompute.recover(board)
        return settings, board

    def sync_our_slot(self, board: DraftBoard) -> DraftBoard:
        """Set our_slot from identities when no picks have been recorded."""
        if board.picks:
            return board
        derived = our_slot_from(load_slots(self.root))
        if derived is None or derived == board.our_slot:
            return board
        opened = board.our_slot is None
        board = set_our_slot(board, derived)
        if opened:
            self.notes.after_setup(board)
        self.persist(board)
        return board

    def persist(self, board: DraftBoard) -> None:
        save_board(self.root, board)
        self.bump()
        self.recompute.schedule(board)


def handle_request(
    app: DraftApp, method: str, path: str, query: str, form: dict[str, str]
) -> _Result:
    """Pure request handling for tests and the HTTP adapter."""
    parsed = urlparse(path)
    route = parsed.path
    qs = parse_qs(query)
    names = names_mode((qs.get("names") or [""])[0])
    if method == "GET":
        if route == "/state":
            settings, board = app.load()
            board = app.sync_our_slot(board)
            payload = build_state(
                board,
                mapping=load_slots(app.root),
                slate=app.recompute.latest,
                generation=app.generation,
                names=names,
                council_running=app.recompute.in_flight,
            )
            return _Result(
                200,
                body=json.dumps(payload),
                content_type="application/json; charset=utf-8",
            )
        if route not in {"/", ""}:
            return _Result(404, body="not found")
        message = (qs.get("msg") or [""])[0]
        typed = (qs.get("q") or [""])[0]
        settings, board = app.load()
        board = app.sync_our_slot(board)
        html = render_page(
            board,
            team_count=settings.team_count,
            available=board.available(app.pool.players),
            message=message,
            query=typed,
            rehearsal=app.rehearsal,
            slate=app.recompute.latest,
            mapping=load_slots(app.root),
            names=names,
            generation=app.generation,
            council_running=app.recompute.in_flight,
        )
        return _Result(200, body=html)
    if method != "POST":
        return _Result(405, body="method not allowed")
    settings, board = app.load()
    if route == "/setup":
        mapping = load_slots(app.root)
        ids = order_from_form(form, settings.team_count)
        if ids:
            mapping = apply_order(mapping, ids, settings.team_count)
            save_order(app.root, {i: mid for i, mid in enumerate(ids, start=1)})
        mapping = merge_form(mapping, form, settings.team_count)
        save_slots(app.root, mapping)
        raw = form.get("our_slot", "").strip()
        derived = our_slot_from(load_slots(app.root))
        if raw.isdigit():
            board = set_our_slot(board, int(raw))
        elif derived is not None:
            board = set_our_slot(board, derived)
        else:
            raise DraftConfigError(
                "mark our team in identities.json (ours=true) or drag "
                "Confidently Incorrect into the order"
            )
        app.notes.after_setup(board)
        app.persist(board)
        return _Result(303, location=redirect_to("room saved"))
    if route == "/order":
        if board.picks:
            raise DraftStateError("cannot reorder seats after picks are recorded")
        ids = order_from_form(form, settings.team_count)
        mapping = apply_order(load_slots(app.root), ids, settings.team_count)
        save_order(
            app.root,
            {index: mid for index, mid in enumerate(ids, start=1)},
        )
        derived = our_slot_from(mapping)
        if derived is None:
            raise DraftConfigError(
                "mark our team in identities.json (ours=true) so the "
                "dragged position becomes our draft slot"
            )
        board = set_our_slot(board, derived)
        app.persist(board)
        return _Result(303, location=redirect_to("order saved"))
    if route == "/labels":
        if board.our_slot is None:
            raise DraftConfigError("set our draft slot before saving team names")
        mapping = merge_form(load_slots(app.root), form, settings.team_count)
        save_slots(app.root, mapping)
        app.bump()
        return _Result(303, location=redirect_to("labels saved"))
    if route == "/pick":
        return _handle_pick(app, board, form)
    if route == "/advance":
        board = advance_unnamed(board)
        if board.complete:
            app.notes.after_complete(board)
        app.persist(board)
        return _Result(303, location=redirect_to(f"clock → {board.upcoming}"))
    if route == "/undo":
        undone = board.picks[-1] if board.picks else None
        board = undo_last(board)
        app.notes.after_undo(board, undone)
        app.persist(board)
        return _Result(303, location=redirect_to("undid last pick"))
    return _Result(404, body="not found")


def _commit_player(app: DraftApp, board: DraftBoard, player: Any) -> DraftBoard:
    slate = app.recompute.latest
    board = record_player(board, player)
    last = board.picks[-1]
    if last.ours and last.kind == "player":
        app.notes.after_our_pick(board, last, slate)
    if board.complete:
        app.notes.after_complete(board)
    app.persist(board)
    return board


def _handle_pick(app: DraftApp, board: DraftBoard, form: dict[str, str]) -> _Result:
    key = form.get("key", "").strip()
    query = form.get("q", "").strip()
    if key:
        player = find_by_key(app.pool.players, key)
        if player is None:
            raise DraftConfigError("that player is not in the pool")
        _commit_player(app, board, player)
        return _Result(303, location=redirect_to(f"recorded {player.name}"))
    available = board.available(app.pool.players)
    matches = match_players(available, query)
    if not matches:
        drafted = match_players(app.pool.players, query)
        if drafted:
            names = ", ".join(player.name for player in drafted)
            raise DraftConfigError(f"already drafted: {names}")
        raise DraftConfigError(f"no pool match for {query!r}")
    if len(matches) == 1:
        player = matches[0]
        _commit_player(app, board, player)
        return _Result(303, location=redirect_to(f"recorded {player.name}"))
    settings = app.settings()
    html = render_page(
        board,
        team_count=settings.team_count,
        available=board.available(app.pool.players),
        message="several matches — pick one",
        candidates=matches,
        query=query,
        rehearsal=app.rehearsal,
        slate=app.recompute.latest,
        mapping=load_slots(app.root),
        generation=app.generation,
    )
    return _Result(200, body=html)


def make_handler(app: DraftApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self._run("GET")

        def do_POST(self) -> None:
            self._run("POST")

        def _run(self, method: str) -> None:
            parsed = urlparse(self.path)
            form = self._form() if method == "POST" else {}
            try:
                with app.lock:
                    result = handle_request(
                        app, method, parsed.path, parsed.query, form
                    )
            except (DraftError, DataError) as exc:
                if method == "POST":
                    self._write(_Result(303, location=redirect_to(str(exc))))
                    return
                self._write(_Result(400, body=_error_page(str(exc))))
                return
            self._write(result)

        def _form(self) -> dict[str, str]:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8")
            parsed = parse_qs(raw, keep_blank_values=True)
            return {
                key: (values[0] if values else "") for key, values in parsed.items()
            }

        def _write(self, result: _Result) -> None:
            self.send_response(result.status)
            if result.location is not None:
                self.send_header("Location", result.location)
                self.end_headers()
                return
            body = (result.body or "").encode("utf-8")
            self.send_header("Content-Type", result.content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def start_server(
    app: DraftApp, *, host: str = "127.0.0.1", port: int = 8765
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(app))


def _error_page(message: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        "<title>Draft board</title></head><body>"
        f"<h1>Draft board</h1><p><strong>{escape(message)}</strong></p>"
        "</body></html>"
    )

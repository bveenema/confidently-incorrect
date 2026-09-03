"""Localhost HTTP handler for draft-board pick entry. No Yahoo, no FastAPI."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from data.league_settings import LeagueSettings, load_league_settings
from data.pool import PlayerPool
from draft.board import (
    DraftBoard,
    advance_unnamed,
    record_player,
    set_our_slot,
    undo_last,
)
from draft.errors import DraftConfigError, DraftError
from draft.io import load_board, save_board
from draft.match import find_by_key, match_players
from draft.page import redirect_to, render_page


@dataclass(frozen=True)
class _Result:
    status: int
    location: str | None = None
    body: str | None = None


def require_snake(settings: LeagueSettings) -> None:
    if settings.draft.type.strip().lower() != "snake":
        raise DraftConfigError(
            f"draft.type {settings.draft.type!r} is not snake. "
            "Set draft.type to snake in $CI_STATE_DIR/league-settings.json."
        )


class DraftApp:
    def __init__(self, root: Path, pool: PlayerPool) -> None:
        self.root = root
        self.pool = pool
        self.lock = threading.Lock()

    def settings(self) -> LeagueSettings:
        settings = load_league_settings(self.root)
        require_snake(settings)
        return settings

    def load(self) -> tuple[LeagueSettings, DraftBoard]:
        settings = self.settings()
        board = load_board(self.root, settings.team_count, settings.draft.rounds)
        return settings, board

    def persist(self, board: DraftBoard) -> None:
        save_board(self.root, board)


def handle_request(
    app: DraftApp, method: str, path: str, query: str, form: dict[str, str]
) -> _Result:
    """Pure request handling for tests and the HTTP adapter."""
    parsed = urlparse(path)
    route = parsed.path
    qs = parse_qs(query)
    if method == "GET":
        if route not in {"/", ""}:
            return _Result(404, body="not found")
        message = (qs.get("msg") or [""])[0]
        typed = (qs.get("q") or [""])[0]
        settings, board = app.load()
        html = render_page(
            board,
            team_count=settings.team_count,
            available=board.available(app.pool.players),
            message=message,
            query=typed,
        )
        return _Result(200, body=html)
    if method != "POST":
        return _Result(405, body="method not allowed")
    _settings, board = app.load()
    if route == "/setup":
        raw = form.get("our_slot", "").strip()
        if not raw.isdigit():
            raise DraftConfigError("our draft slot must be an integer")
        board = set_our_slot(board, int(raw))
        app.persist(board)
        return _Result(303, location=redirect_to("slot saved"))
    if route == "/pick":
        return _handle_pick(app, board, form)
    if route == "/advance":
        board = advance_unnamed(board)
        app.persist(board)
        return _Result(303, location=redirect_to(f"clock → {board.upcoming}"))
    if route == "/undo":
        board = undo_last(board)
        app.persist(board)
        return _Result(303, location=redirect_to("undid last pick"))
    return _Result(404, body="not found")


def _handle_pick(app: DraftApp, board: DraftBoard, form: dict[str, str]) -> _Result:
    key = form.get("key", "").strip()
    query = form.get("q", "").strip()
    if key:
        player = find_by_key(app.pool.players, key)
        if player is None:
            raise DraftConfigError("that player is not in the pool")
        board = record_player(board, player)
        app.persist(board)
        return _Result(303, location=redirect_to(f"recorded {player.name}"))
    matches = match_players(app.pool.players, query)
    if not matches:
        raise DraftConfigError(f"no pool match for {query!r}")
    if len(matches) == 1:
        player = matches[0]
        board = record_player(board, player)
        app.persist(board)
        return _Result(303, location=redirect_to(f"recorded {player.name}"))
    settings = app.settings()
    html = render_page(
        board,
        team_count=settings.team_count,
        available=board.available(app.pool.players),
        message="several matches — pick one",
        candidates=matches,
        query=query,
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
            except DraftError as exc:
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
            self.send_header("Content-Type", "text/html; charset=utf-8")
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

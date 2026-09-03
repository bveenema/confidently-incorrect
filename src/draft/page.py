"""Unstyled HTML contract for draft-night pick entry.

D-80: this is fields, POST actions, and a state dump — not a designed
board. Issue 10 owns glanceable tiers/roster layout.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from data.pool import PooledPlayer
from draft.board import DraftBoard, RecordedPick
from draft.match import player_key


def render_page(
    board: DraftBoard,
    *,
    team_count: int,
    available: tuple[PooledPlayer, ...],
    message: str = "",
    candidates: tuple[PooledPlayer, ...] = (),
    query: str = "",
) -> str:
    if board.our_slot is None:
        return _setup(team_count, message)
    return _board(
        board,
        available=available,
        message=message,
        candidates=candidates,
        query=query,
    )


def _setup(team_count: int, message: str) -> str:
    return _wrap(
        "<h1>Draft board</h1>"
        f"{_flash(message)}"
        f"<p>Team count: {team_count} "
        "(from $CI_STATE_DIR/league-settings.json). "
        "Edit that file if the room grew; this page re-reads it.</p>"
        '<form method="post" action="/setup">'
        "<p><label>Our draft slot "
        f'<input name="our_slot" type="number" min="1" max="{team_count}" '
        "required autofocus></label></p>"
        '<p><button type="submit">Start</button></p>'
        "</form>"
    )


def _board(
    board: DraftBoard,
    *,
    available: tuple[PooledPlayer, ...],
    message: str,
    candidates: tuple[PooledPlayer, ...],
    query: str,
) -> str:
    clock = board.on_the_clock()
    ours = board.next_ours()
    turn = " TURN" if board.turn() else ""
    done = " Draft complete." if board.complete else ""
    clock_txt = "—" if clock is None else str(clock)
    ours_txt = "—" if ours is None else str(ours)
    upcoming = "—" if board.complete else str(board.upcoming)
    parts = [
        "<h1>Draft board</h1>",
        _flash(message),
        f"<p><strong>Next pick: {upcoming}</strong> · "
        f"On the clock: slot {clock_txt} · "
        f"Our next: {ours_txt} · "
        f"Our slot: {board.our_slot} · "
        f"{board.team_count} teams, {board.rounds} rounds."
        f"<strong>{escape(turn)}</strong>{escape(done)}</p>",
    ]
    if not board.complete:
        parts.append(
            '<form method="post" action="/pick">'
            "<p><label>Player "
            f'<input name="q" value="{escape(query, quote=True)}" '
            "autofocus></label> "
            '<button type="submit">Record pick</button></p>'
            "</form>"
        )
        if clock != board.our_slot:
            parts.append(
                '<form method="post" action="/advance">'
                '<p><button type="submit">Other team picked (unnamed)</button> '
                "— advances the clock without removing anyone from available."
                "</p></form>"
            )
    if candidates:
        parts.append(f"<h2>Which {escape(query) or 'player'}?</h2><ul>")
        for player in candidates:
            key = escape(player_key(player), quote=True)
            label = escape(_player_label(player))
            parts.append(
                "<li>"
                '<form method="post" action="/pick">'
                f'<input type="hidden" name="key" value="{key}">'
                f'<button type="submit">{label}</button>'
                "</form></li>"
            )
        parts.append("</ul>")
    if board.picks:
        parts.append(
            '<form method="post" action="/undo">'
            '<p><button type="submit">Undo last pick</button></p>'
            "</form>"
        )
    parts.append(_picks_section(board.picks))
    parts.append(_roster_section(board.our_roster()))
    parts.append(_available_section(available))
    return _wrap("".join(parts))


def _picks_section(picks: tuple[RecordedPick, ...]) -> str:
    if not picks:
        return "<h2>Picks</h2><p>None yet.</p>"
    rows = ["<h2>Picks</h2><ol>"]
    for pick in picks:
        if pick.kind == "unnamed":
            flag = " (us)" if pick.ours else ""
            label = f"#{pick.overall} slot {pick.slot} — unnamed{flag}"
        else:
            flag = " (us)" if pick.ours else ""
            label = (
                f"#{pick.overall} slot {pick.slot} — "
                f"{pick.name} {pick.position} {pick.team}{flag}"
            )
        rows.append(f"<li>{escape(label)}</li>")
    rows.append("</ol>")
    return "".join(rows)


def _roster_section(roster: tuple[RecordedPick, ...]) -> str:
    if not roster:
        return "<h2>Our roster</h2><p>None yet.</p>"
    items = "".join(
        f"<li>{escape(f'#{p.overall} {p.name} {p.position} {p.team}')}</li>"
        for p in roster
    )
    return f"<h2>Our roster</h2><ol>{items}</ol>"


def _available_section(available: tuple[PooledPlayer, ...]) -> str:
    rows = [
        f"<h2>Available ({len(available)})</h2>",
        "<p>Unnamed clock advances do not remove players. "
        "Glanceable tiers are issue 10.</p>",
    ]
    if not available:
        rows.append("<p>None left in the pool.</p>")
        return "".join(rows)
    rows.append("<ol>")
    shown = available[:80]
    for player in shown:
        rows.append(f"<li>{escape(_player_label(player))}</li>")
    rows.append("</ol>")
    if len(available) > len(shown):
        rows.append(f"<p>…and {len(available) - len(shown)} more.</p>")
    return "".join(rows)


def _player_label(player: PooledPlayer) -> str:
    extra = ""
    if player.value_rank is not None:
        extra = f" #{player.value_rank}"
    return f"{player.name} {player.position} {player.team}{extra}"


def _flash(message: str) -> str:
    if not message:
        return ""
    return f"<p><strong>{escape(message)}</strong></p>"


def _wrap(body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        "<title>Draft board</title>"
        "</head><body>"
        f"{body}"
        "</body></html>"
    )


def redirect_to(message: str = "", query: str = "") -> str:
    params: list[str] = []
    if message:
        params.append(f"msg={quote(message)}")
    if query:
        params.append(f"q={quote(query)}")
    suffix = ("?" + "&".join(params)) if params else ""
    return "/" + suffix

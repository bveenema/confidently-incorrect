"""Draft-night pick entry page. D-80: Fable owns layout; this is the contract."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from data.pool import PooledPlayer
from draft.board import DraftBoard, RecordedPick
from draft.identities import our_member
from draft.match import player_key
from draft.recompute import DraftSlate, ours_on_the_clock
from draft.slots import SlotMap, display_for, empty_map, our_slot_from, pseudonym_for

DASH = "—"


def render_page(
    board: DraftBoard,
    *,
    team_count: int,
    available: tuple[PooledPlayer, ...],
    message: str = "",
    candidates: tuple[PooledPlayer, ...] = (),
    query: str = "",
    rehearsal: bool = False,
    slate: DraftSlate | None = None,
    mapping: SlotMap | None = None,
    names: str = "display",
    generation: int = 0,
    council_running: bool | None = None,
) -> str:
    slots = mapping if mapping is not None else empty_map()
    if board.our_slot is None:
        return _setup(
            team_count,
            message,
            rehearsal=rehearsal,
            mapping=slots,
            names=names,
        )
    return _board(
        board,
        available=available,
        message=message,
        candidates=candidates,
        query=query,
        rehearsal=rehearsal,
        slate=slate,
        mapping=slots,
        names=names,
        generation=generation,
        council_running=council_running,
    )


def _setup(
    team_count: int,
    message: str,
    *,
    rehearsal: bool = False,
    mapping: SlotMap,
    names: str,
) -> str:
    derived = our_slot_from(mapping)
    slot_field = ""
    if derived is None:
        slot_field = (
            '<p class="field"><label>Our draft slot '
            f'<input name="our_slot" type="number" min="1" max="{team_count}" '
            "required autofocus></label></p>"
        )
    return _wrap(
        '<div class="top">'
        f"{_rehearsal_banner(rehearsal)}"
        '<div class="bar"><div class="brandline"><h1>Draft board</h1>'
        '<p class="meta">Setup</p>'
        f"{_heartbeat()}"
        "</div></div></div>"
        '<main class="wrap setup">'
        f"{_flash(message)}"
        '<section class="card">'
        f'<p class="muted">Team count: {team_count} '
        "(from $CI_STATE_DIR/league-settings.json). "
        "Edit that file if the room grew; this page re-reads it. "
        "Drag the room into snake order. Our seat is wherever "
        "Confidently Incorrect lands — you do not type a slot number.</p>"
        '<form method="post" action="/setup" id="order-form">'
        f"{slot_field}"
        f"{_order_list(team_count, mapping, names)}"
        '<p><button type="submit" class="primary">Open the room</button></p>'
        "</form></section></main>",
        names=names,
        phase="setup",
        generation=0,
    )


def _board(
    board: DraftBoard,
    *,
    available: tuple[PooledPlayer, ...],
    message: str,
    candidates: tuple[PooledPlayer, ...],
    query: str,
    rehearsal: bool = False,
    slate: DraftSlate | None = None,
    mapping: SlotMap,
    names: str,
    generation: int,
    council_running: bool | None = None,
) -> str:
    clock = board.on_the_clock()
    ours = board.next_ours()
    clock_txt = DASH if clock is None else display_for(mapping, clock, names=names)
    ours_txt = DASH if ours is None else str(ours)
    upcoming = DASH if board.complete else str(board.upcoming)
    our_label = (
        display_for(mapping, board.our_slot, names=names)
        if board.our_slot is not None
        else DASH
    )
    phase = (
        "complete"
        if board.complete
        else ("disambiguating" if candidates else "drafting")
    )
    panel_matches = (
        slate is not None
        and slate.panel is not None
        and slate.panel.packet_hash == slate.packet_hash
    )
    if council_running is None:
        council_running = (
            phase == "drafting"
            and ours_on_the_clock(board)
            and (slate is None or (slate.source == "fallback" and not panel_matches))
        )
    top = [
        '<div class="top">',
        _rehearsal_banner(rehearsal),
        '<div class="bar">',
        '<div class="brandline"><h1>Draft board</h1>',
        f'<p class="meta">Our slot: <b>{escape(our_label)}</b> · '
        f"{board.team_count} teams · {board.rounds} rounds</p>",
        _heartbeat(),
        "</div>",
        _clock_tiles(
            upcoming=upcoming,
            clock_txt=clock_txt,
            clock_ours=clock is not None and clock == board.our_slot,
            ours_txt=ours_txt,
            turn=bool(board.turn()),
            complete=board.complete,
        ),
    ]
    if not board.complete:
        top.append(
            '<form method="post" action="/pick" class="pick">'
            "<label>Player "
            f'<input name="q" value="{escape(query, quote=True)}" '
            'placeholder="type a name, Enter records the pick" '
            'autocomplete="off" autofocus></label> '
            '<button type="submit" class="primary">Record pick</button>'
            "</form>"
        )
    top.append("</div></div>")
    parts = ["".join(top), '<main class="wrap">', _flash(message)]
    actions: list[str] = []
    if not board.complete and clock != board.our_slot:
        actions.append(
            '<form method="post" action="/advance">'
            '<button type="submit">Other team picked (unnamed)</button></form>'
            '<span class="hint">— advances the clock without removing anyone '
            "from available.</span>"
        )
    if board.picks:
        actions.append(
            '<form method="post" action="/undo">'
            '<button type="submit">Undo last pick</button></form>'
        )
    if actions:
        parts.append(f'<div class="actions">{"".join(actions)}</div>')
    if candidates:
        parts.append(f'<h2>Which {escape(query) or "player"}?</h2><ul class="cands">')
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
    parts.append('<div class="cols">')
    parts.append(
        '<div id="slate-region">'
        f"{_slate_section(slate, council_running=council_running)}</div>"
    )
    parts.append("<div>")
    parts.append(_roster_section(board.our_roster()))
    parts.append(_picks_section(board.picks, mapping, names))
    parts.append("</div></div>")
    if names != "pseudonym":
        if not board.picks:
            parts.append(_order_form(board.team_count, mapping, names))
        else:
            parts.append(_labels_form(board.team_count, mapping))
    parts.append(_available_section(available))
    parts.append("</main>")
    return _wrap(
        "".join(parts),
        names=names,
        phase=phase,
        generation=generation,
    )


def _heartbeat() -> str:
    return (
        '<p id="heartbeat"><span id="updated-ago">updated just now</span>'
        '<span id="disconnected" hidden> disconnected</span></p>'
    )


def _clock_tiles(
    *,
    upcoming: str,
    clock_txt: str,
    clock_ours: bool,
    ours_txt: str,
    turn: bool,
    complete: bool,
) -> str:
    """Mirrors clockHtml() in _SCRIPT. Change both together."""
    ours_cls = " ours" if clock_ours else ""
    tag = '<span class="tag">us</span>' if clock_ours else ""
    tiles = [
        '<div class="tile"><span class="k">Next pick</span>'
        f'<b class="v" id="next-pick">{escape(upcoming)}</b></div>',
        f'<div class="tile clock{ours_cls}"><span class="k">On the clock</span>'
        f'<b class="v who">{escape(clock_txt)}</b>{tag}</div>',
        '<div class="tile"><span class="k">Our next</span>'
        f'<b class="v">{escape(ours_txt)}</b></div>',
    ]
    if complete:
        tiles.append(
            '<div class="tile done"><span class="k">Status</span>'
            '<b class="v">Draft complete</b></div>'
        )
    elif turn:
        tiles.append(
            '<div class="tile turn"><span class="k">Status</span>'
            '<b class="v">TURN</b></div>'
        )
    return f'<div id="clock-line" class="tiles">{"".join(tiles)}</div>'


def _order_form(team_count: int, mapping: SlotMap, names: str) -> str:
    return (
        '<section class="card" id="room-order">'
        "<h2>Draft order</h2>"
        '<p class="muted">Drag to match the room. Our pick is wherever '
        "this team sits.</p>"
        '<form method="post" action="/order" id="order-form">'
        f"{_order_list(team_count, mapping, names)}"
        '<p><button type="submit">Save draft order</button></p>'
        "</form></section>"
    )


def _order_list(team_count: int, mapping: SlotMap, names: str) -> str:
    ours = our_member(mapping.identities)
    ours_id = ours.member_id if ours is not None else ""
    items: list[str] = []
    used: set[str] = set()
    index = 0
    for slot in range(1, team_count + 1):
        label = mapping.label(slot)
        if label is None or not label.member_id:
            continue
        index += 1
        used.add(label.member_id)
        shown = display_for(mapping, slot, names=names)
        is_us = label.member_id == ours_id
        items.append(_order_item(index, label.member_id, shown, is_us))
    for member in sorted(
        mapping.identities.members.values(), key=lambda m: m.member_id
    ):
        if member.member_id in used:
            continue
        index += 1
        shown = (
            member.pseudonym
            if names == "pseudonym"
            else (member.display or member.pseudonym)
        )
        items.append(
            _order_item(index, member.member_id, shown, member.member_id == ours_id)
        )
    return f'<ol id="draft-order">{"".join(items)}</ol>'


def _order_item(index: int, member_id: str, shown: str, is_us: bool) -> str:
    us = ' data-ours="true"' if is_us else ""
    tag = '<span class="tag">us</span>' if is_us else ""
    mid = escape(member_id, quote=True)
    return (
        f'<li draggable="true" tabindex="0" data-member-id="{mid}"{us}>'
        f'<input type="hidden" name="member_{index}" value="{mid}">'
        '<span class="grip" aria-hidden="true"></span>'
        f'<span class="pos">{index}</span> '
        f'<span class="name">{escape(shown)}</span>{tag}'
        "</li>"
    )


def _labels_form(team_count: int, mapping: SlotMap) -> str:
    rows = [
        '<details class="card"><summary>Room — team names '
        "(this page only; notes and kb.db use slot codes)</summary>",
        '<form method="post" action="/labels"><div class="room">',
    ]
    for slot in range(1, team_count + 1):
        current = mapping.label(slot)
        value = current.display if current else ""
        rows.append(
            "<p><label>"
            f"{escape(default_slot_heading(slot, mapping))} "
            f'<input name="display_{slot}" value="{escape(value, quote=True)}">'
            "</label></p>"
        )
    rows.append(
        '</div><p class="room-save"><button type="submit">Save team names'
        "</button></p></form></details>"
    )
    return "".join(rows)


def default_slot_heading(slot: int, mapping: SlotMap) -> str:
    return f"Slot {slot} ({pseudonym_for(mapping, slot)})"


def _picks_section(
    picks: tuple[RecordedPick, ...], mapping: SlotMap, names: str
) -> str:
    if not picks:
        return (
            '<section class="card"><h2>Picks</h2>'
            '<p class="muted">None yet.</p></section>'
        )
    rows = ['<section class="card"><h2>Picks</h2><ol class="plain picks">']
    for pick in reversed(picks):
        seat = display_for(mapping, pick.slot, names=names)
        flag = " (us)" if pick.ours else ""
        if pick.kind == "unnamed":
            label = f"#{pick.overall} {seat} — unnamed{flag}"
        else:
            label = (
                f"#{pick.overall} {seat} — "
                f"{pick.name} {pick.position} {pick.team}{flag}"
            )
        cls = ' class="us"' if pick.ours else ""
        rows.append(f"<li{cls}>{escape(label)}</li>")
    rows.append("</ol></section>")
    return "".join(rows)


def _roster_section(roster: tuple[RecordedPick, ...]) -> str:
    if not roster:
        return (
            '<section class="card"><h2>Our roster</h2>'
            '<p class="muted">None yet.</p></section>'
        )
    items = "".join(
        f"<li>{escape(f'#{p.overall} {p.name} {p.position} {p.team}')}</li>"
        for p in roster
    )
    return (
        '<section class="card"><h2>Our roster</h2>'
        f'<ol class="plain">{items}</ol></section>'
    )


def _available_section(available: tuple[PooledPlayer, ...]) -> str:
    rows = [
        '<section class="avail"><div class="card-h">'
        f"<h2>Available ({len(available)})</h2>"
        '<span class="muted">Unnamed clock advances do not remove players.'
        "</span></div>",
    ]
    if not available:
        rows.append('<p class="muted">None left in the pool.</p></section>')
        return "".join(rows)
    by_pos: dict[str, list[PooledPlayer]] = {}
    incomplete: list[PooledPlayer] = []
    for player in available:
        if player.scoring_incomplete:
            incomplete.append(player)
            continue
        by_pos.setdefault(player.position, []).append(player)
    rows.append('<div class="avail-grid">')
    for position in sorted(by_pos):
        rows.append(f'<div class="pos"><h3>{escape(position)}</h3><ol>')
        shown = by_pos[position][:20]
        for player in shown:
            rows.append(f"<li>{escape(_player_label(player))}</li>")
            if player.tier_break_after:
                rows.append('<li class="tier"><em>tier break</em></li>')
        rows.append("</ol>")
        if len(by_pos[position]) > len(shown):
            rows.append(
                f'<p class="more">…and {len(by_pos[position]) - len(shown)} more.</p>'
            )
        rows.append("</div>")
    if incomplete:
        rows.append('<div class="pos"><h3>Incomplete scoring</h3><ol>')
        for player in incomplete[:20]:
            rows.append(f"<li>{escape(_player_label(player))}</li>")
        rows.append("</ol></div>")
    rows.append("</div></section>")
    return "".join(rows)


def _player_label(player: PooledPlayer) -> str:
    extra = ""
    if player.value_rank is not None:
        extra = f" #{player.value_rank}"
    return f"{player.name} {player.position} {player.team}{extra}"


def _copy_name_button(name: str) -> str:
    return (
        '<button type="button" class="copy-name" '
        f'data-copy-name="{escape(name, quote=True)}" '
        'aria-label="Copy player name" title="Copy name">'
        '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
        '<rect x="5" y="5" width="8" height="9" rx="1" fill="none" '
        'stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H10" fill="none" '
        'stroke="currentColor" stroke-width="1.4"/>'
        "</svg></button>"
    )


_RUNNING = '<p class="running"><span class="dot"></span>council running…</p>'


def _slate_section(slate: DraftSlate | None, *, council_running: bool = False) -> str:
    """Mirrors slateHtml() in _SCRIPT. Change both together."""
    rows = ['<section class="card slate"><div class="card-h"><h2>Council slate</h2>']
    running = _RUNNING if council_running else ""
    if slate is None or not slate.items:
        rows.append(
            f"</div>{running}"
            '<p class="muted">No ranked list yet — enter our slot, '
            "then wait one recompute.</p></section>"
        )
        return "".join(rows)
    if slate.source == "fallback":
        rows.append('<span class="badge warn">tier fallback</span>')
    else:
        rows.append('<span class="badge ok">council</span>')
    if slate.failure_mode:
        rows.append(f'<span class="fail">{escape(slate.failure_mode)}</span>')
    rows.append(f'</div>{running}<ol class="slate-list">')
    for item in slate.items:
        rows.append(
            "<li>"
            f'<span class="rk">{item.rank}</span>'
            f'<span class="nm">{escape(item.name)}</span>'
            f'<span class="pt">{escape(item.position)} {escape(item.team)}</span>'
            f"{_copy_name_button(item.name)}"
            f"<code>{escape(item.player_key)}</code>"
            "</li>"
        )
    rows.append("</ol>")
    panel = slate.panel
    if panel is not None and panel.packet_hash == slate.packet_hash:
        rows.append('<div class="panel">')
        if panel.decision is not None:
            rows.append("<h3>GM rationale</h3>")
            rows.append(f'<p class="rationale">{escape(panel.decision.rationale)}</p>')
            chips = [
                f'<span class="chip">adopted: {escape(p)}</span>'
                for p in panel.decision.adopted_from
            ] + [
                f'<span class="chip over">overruled: {escape(p)}</span>'
                for p in panel.decision.overruled
            ]
            if chips:
                rows.append(f'<p class="chips">{"".join(chips)}</p>')
        if panel.briefs:
            rows.append("<h3>Specialists</h3>")
            for brief in panel.briefs:
                cls = " absent" if brief.absent else ""
                rows.append(
                    f'<div class="brief{cls}"><div class="brief-h">'
                    f"<strong>{escape(brief.persona)}</strong>"
                )
                if brief.confidence is not None:
                    rows.append(
                        f'<span class="conf">confidence {brief.confidence}</span>'
                    )
                if brief.absent:
                    rows.append('<span class="abs">absent</span>')
                rows.append("</div>")
                if brief.reasoning:
                    rows.append(f"<p>{escape(brief.reasoning)}</p>")
                if brief.dissent:
                    rows.append(
                        f'<p class="dissent">Dissent: {escape(brief.dissent)}</p>'
                    )
                rows.append("</div>")
        rows.append("</div>")
    rows.append("</section>")
    return "".join(rows)


def _rehearsal_banner(rehearsal: bool) -> str:
    if not rehearsal:
        return ""
    return (
        '<p class="rehearsal"><strong>REHEARSAL</strong> '
        "<small>— writes go to this --state-dir, not the live runtime root."
        "</small></p>"
    )


def _flash(message: str) -> str:
    if not message:
        return ""
    return f'<p class="flash"><strong>{escape(message)}</strong></p>'


def _wrap(body: str, *, names: str, phase: str, generation: int) -> str:
    names_q = f"?names={quote(names)}" if names == "pseudonym" else ""
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Draft board</title>"
        f"<style>{_STYLE}</style>"
        "</head>"
        f'<body data-phase="{escape(phase, quote=True)}" '
        f'data-names="{escape(names, quote=True)}" '
        f'data-generation="{generation}">'
        f"{body}"
        f'<footer class="foot"><a href="/{names_q}">refresh</a>'
        + (
            ' · <a href="/?names=pseudonym">pseudonym view</a>'
            if names != "pseudonym"
            else ' · <a href="/">team-name view</a>'
        )
        + "</footer>"
        f"<script>{_SCRIPT}</script>"
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


# Token language shared with assets/admin-console-mockup.html. System UI stack,
# no webfonts, no CDN — the stdlib server has no static route and the page must
# render fully offline. Lines stay under 88 columns for ruff E501.
_STYLE = """
:root{--page:#FAFAF8;--card:#FFFFFF;--sunk:#F4F3F0;--line:#E5E3DE;
--line-2:#D2CFC8;--ink:#1F1E1C;--ink-2:#6B6862;--ink-3:#96928B;
--brand:#FF7F2A;--brand-bg:#FFF0E6;--ok:#0F6E56;--ok-bg:#E1F5EE;
--bad:#A32D2D;--bad-bg:#FCEBEB;--warn:#854F0B;--warn-bg:#FBF1DF;--radius:8px}
@media (prefers-color-scheme:dark){:root{--page:#161512;--card:#1E1D1A;
--sunk:#232220;--line:#302E2A;--line-2:#403D38;--ink:#EFEDE8;--ink-2:#A5A199;
--ink-3:#7A766F;--brand-bg:#3A2412;--ok:#5DCAA5;--ok-bg:#123329;--bad:#F09595;
--bad-bg:#3A1717;--warn:#EF9F27;--warn-bg:#3A2A0F}}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--page);color:var(--ink);font-size:15px;line-height:1.5;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
-webkit-font-smoothing:antialiased}
h1{font-size:16px;font-weight:600;margin:0}
h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
color:var(--ink-2);margin:0 0 10px}
h3{font-size:13px;font-weight:600;color:var(--ink-2);margin:14px 0 6px}
p{margin:0 0 8px}
a{color:var(--brand)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
font-size:12px;color:var(--ink-3)}
input,button{font:inherit}
input{background:var(--card);color:var(--ink);border:1px solid var(--line-2);
border-radius:var(--radius);padding:8px 10px;min-width:0}
input:focus{outline:2px solid var(--brand);outline-offset:1px;
border-color:var(--brand)}
button{background:var(--sunk);color:var(--ink);border:1px solid var(--line-2);
border-radius:var(--radius);padding:8px 14px;cursor:pointer}
button:hover{border-color:var(--ink-3)}
button.primary{background:var(--brand);border-color:var(--brand);color:#fff;
font-weight:600}
.top{position:sticky;top:0;z-index:10;background:var(--card);
border-bottom:1px solid var(--line)}
.rehearsal{background:var(--bad);color:#fff;text-align:center;font-weight:700;
letter-spacing:.08em;padding:6px 12px;margin:0}
.rehearsal small{font-weight:400;letter-spacing:0;opacity:.9}
.bar{max-width:1100px;margin:0 auto;padding:10px 20px 12px;display:grid;gap:10px}
.brandline{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
.meta{color:var(--ink-2);font-size:13px;margin:0}
#heartbeat{margin:0 0 0 auto;font-size:12px;color:var(--ink-3)}
#disconnected{color:var(--bad);font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:10px}
.tile{background:var(--sunk);border-radius:var(--radius);padding:10px 14px;
min-width:0}
.tile .k{display:block;font-size:12px;color:var(--ink-2)}
.tile .v{display:block;font-size:30px;line-height:1.15;font-weight:600;
font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.tile .v.who{font-size:22px}
.tile.ours{background:var(--brand-bg);box-shadow:inset 0 0 0 2px var(--brand)}
.tile.ours .v{color:var(--brand)}
.tile.turn{background:var(--brand);color:#fff}
.tile.turn .k{color:rgba(255,255,255,.85)}
.tile.done{background:var(--ok-bg)}
.tile.done .v{color:var(--ok);font-size:20px}
.tile.stale{background:var(--warn-bg);color:var(--warn);text-decoration:none;
display:flex;align-items:center;font-weight:600}
.tag{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;
background:var(--brand);color:#fff;border-radius:999px;padding:1px 8px;
margin-top:4px}
.pick{display:flex;gap:8px;align-items:center;margin:0}
.pick label{flex:1;display:flex;align-items:center;gap:10px;font-weight:600}
.pick input{flex:1;font-size:20px;padding:10px 12px}
.pick button{font-size:16px;padding:11px 18px}
.wrap{max-width:1100px;margin:0 auto;padding:16px 20px 40px}
.setup{max-width:680px}
.field label{display:flex;align-items:center;gap:10px;font-weight:600}
.field input{font-size:20px;width:110px}
.flash{background:var(--warn-bg);color:var(--warn);border-left:4px solid var(--warn);
padding:10px 14px;border-radius:var(--radius);margin:0 0 14px}
.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:0 0 16px}
.actions form{margin:0}
.actions .hint{color:var(--ink-3);font-size:13px}
.cands{list-style:none;padding:0;margin:0 0 16px;display:flex;flex-wrap:wrap;
gap:8px}
.cands form{margin:0}
.cands button{font-size:16px;padding:10px 16px;background:var(--card)}
.cols{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:16px;
align-items:start}
@media(max-width:820px){.cols{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 16px;margin-bottom:16px}
.card-h{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.card-h h2{margin:0}
.badge{font-size:11px;font-weight:700;text-transform:uppercase;
letter-spacing:.05em;border-radius:999px;padding:2px 9px}
.badge.ok{background:var(--ok-bg);color:var(--ok)}
.badge.warn{background:var(--warn-bg);color:var(--warn)}
.fail{font-size:12px;color:var(--bad);
font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.running{display:flex;align-items:center;gap:8px;color:var(--warn);
font-weight:600;background:var(--warn-bg);padding:6px 10px;
border-radius:var(--radius)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--warn);
animation:pulse 1s ease-in-out infinite}
@keyframes pulse{50%{opacity:.25}}
.slate-list{list-style:none;margin:0;padding:0}
.slate-list li{display:grid;
grid-template-columns:2rem minmax(0,1fr) auto 28px;
gap:2px 10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.slate-list li:last-child{border-bottom:0}
.slate-list .rk{grid-column:1;grid-row:1}
.slate-list .nm{grid-column:2;grid-row:1}
.slate-list .pt{grid-column:3;grid-row:1}
.slate-list .copy-name{grid-column:4;grid-row:1}
.slate-list li:first-child .nm{font-size:22px}
.slate-list code{grid-column:2/5;grid-row:2}
.copy-name{display:inline-flex;align-items:center;justify-content:center;
width:28px;height:28px;padding:0;background:transparent;
border-color:transparent;color:var(--ink-3)}
.copy-name:hover{color:var(--brand);border-color:var(--line-2);
background:var(--sunk)}
.copy-name.copied{color:var(--ok)}
.rk{font-weight:700;color:var(--ink-3);font-variant-numeric:tabular-nums}
.nm{font-weight:600;font-size:16px}
.pt{color:var(--ink-2);font-size:13px}
.panel{border-top:1px solid var(--line);margin-top:10px}
.rationale{font-size:15px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:12px;background:var(--sunk);border-radius:999px;padding:2px 9px;
color:var(--ink-2)}
.chip.over{background:var(--bad-bg);color:var(--bad)}
.brief{padding:8px 0;border-top:1px dashed var(--line)}
.brief-h{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.brief-h .conf{font-size:12px;color:var(--ink-2)}
.brief-h .abs{font-size:11px;text-transform:uppercase;color:var(--bad);
font-weight:700}
.brief.absent{opacity:.6}
.brief p{font-size:14px;margin:4px 0 0}
.dissent{color:var(--bad)}
.muted{color:var(--ink-3)}
ol.plain{margin:0;padding-left:26px}
ol.plain li{padding:3px 0;border-bottom:1px solid var(--line)}
ol.plain li:last-child{border-bottom:0}
ol.picks{list-style:none;padding-left:0}
ol.picks li.us{color:var(--brand);font-weight:600}
details.card summary{cursor:pointer;font-weight:600;color:var(--ink-2);
font-size:13px}
.room{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
gap:8px 14px;margin-top:10px}
.room p{margin:0}
.room label{display:grid;gap:2px;font-size:12px;color:var(--ink-2)}
.room-save{margin-top:12px}
#draft-order{list-style:none;margin:10px 0 14px;padding:0;display:grid;gap:6px}
#draft-order li{display:flex;align-items:center;gap:10px;padding:9px 12px;
background:var(--sunk);border:1px solid var(--line);border-radius:var(--radius);
cursor:grab;user-select:none;-webkit-user-select:none;
transition:box-shadow .12s ease,border-color .12s ease}
#draft-order li:hover{border-color:var(--line-2);
box-shadow:0 1px 3px rgba(0,0,0,.08)}
#draft-order li:active{cursor:grabbing}
#draft-order li:focus-visible{outline:2px solid var(--brand);outline-offset:1px}
#draft-order .grip{flex:none;width:10px;height:15px;opacity:.75;
background-image:radial-gradient(circle,var(--ink-3) 1.3px,transparent 1.7px);
background-size:5px 5px}
#draft-order .pos{background:none;border:0;border-radius:0;padding:0;
min-width:24px;text-align:right;font-weight:700;color:var(--ink-3);
font-variant-numeric:tabular-nums;font-size:14px}
#draft-order .name{flex:1;min-width:0;font-weight:600;font-size:16px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#draft-order .tag{margin:0}
#draft-order li[data-ours="true"]{background:var(--brand-bg);
border-color:var(--brand);box-shadow:inset 0 0 0 1px var(--brand)}
#draft-order li[data-ours="true"] .pos,
#draft-order li[data-ours="true"] .name{color:var(--brand)}
#draft-order li[data-ours="true"] .grip{
background-image:radial-gradient(circle,var(--brand) 1.3px,transparent 1.7px)}
#draft-order.active li{cursor:grabbing}
#draft-order li.dragging{opacity:.4;background:var(--card);
border:1px dashed var(--brand);box-shadow:none}
#draft-order li.dragging *{visibility:hidden}
#order-form .dirty-hint{display:none;color:var(--warn);font-size:13px;
margin-left:10px}
#order-form.dirty .dirty-hint{display:inline}
.avail-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
gap:14px}
.pos{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:12px 14px}
.pos h3{margin:0 0 6px;font-size:14px;color:var(--ink)}
.pos ol{margin:0;padding-left:26px;font-size:14px}
.pos li{padding:2px 0}
.pos li.tier{list-style:none;margin-left:-26px;color:var(--ink-3);font-size:11px;
text-transform:uppercase;letter-spacing:.06em;border-top:1px dashed var(--line-2);
padding:2px 0 0;margin-top:4px}
.pos .more{color:var(--ink-3);font-size:12px;margin:6px 0 0}
.foot{max-width:1100px;margin:0 auto;padding:0 20px 30px;font-size:13px;
color:var(--ink-3)}
"""


# Polls GET /state (D-80). Patches #clock-line and #slate-region only, and only
# when generation changes. Never touches the pick input, the candidate list, or
# the setup form; never reloads the page.
#
# The first IIFE is the draft-order drag list (D-80). It only touches
# #draft-order and #order-form; the poll below never touches those, so the two
# cannot fight. Rows move live on dragover, so the dashed ghost row is the drop
# target. Hidden member_K inputs and .pos numbers are rewritten after every
# move, so a plain form submit carries the new order.
_SCRIPT = """
(function(){
var list=document.getElementById('draft-order');
if(!list)return;
var form=document.getElementById('order-form');
var dragging=null;
var dirty=false;
function rows(){
return Array.prototype.slice.call(list.querySelectorAll('li[data-member-id]'));}
function rowOf(t){
while(t&&t!==list){
if(t.nodeType===1&&t.hasAttribute('data-member-id'))return t;
t=t.parentNode;}
return null;}
function renumber(){
rows().forEach(function(li,i){
var n=String(i+1);
var pos=li.querySelector('.pos');if(pos){pos.textContent=n;}
var inp=li.querySelector('input[type=hidden]');
if(inp){inp.name='member_'+n;inp.value=li.getAttribute('data-member-id');}});}
function markDirty(){
renumber();
if(dirty||!form)return;
dirty=true;
form.classList.add('dirty');
var btn=form.querySelector('button[type=submit]');
if(!btn)return;
btn.classList.add('primary');
var hint=document.createElement('span');
hint.className='dirty-hint';
hint.textContent='order changed \\u2014 not saved yet';
btn.parentNode.insertBefore(hint,btn.nextSibling);}
function finish(){
if(dragging){dragging.classList.remove('dragging');}
dragging=null;
list.classList.remove('active');
markDirty();}
list.addEventListener('dragstart',function(e){
var li=rowOf(e.target);
if(!li)return;
dragging=li;
list.classList.add('active');
setTimeout(function(){if(dragging===li){li.classList.add('dragging');}},0);
if(e.dataTransfer){
e.dataTransfer.effectAllowed='move';
try{e.dataTransfer.setData('text/plain',li.getAttribute('data-member-id'));}
catch(err){}}});
list.addEventListener('dragover',function(e){
if(!dragging)return;
e.preventDefault();
if(e.dataTransfer){e.dataTransfer.dropEffect='move';}
var li=rowOf(e.target);
if(!li||li===dragging)return;
var r=li.getBoundingClientRect();
var after=e.clientY>r.top+r.height/2;
list.insertBefore(dragging,after?li.nextSibling:li);});
list.addEventListener('drop',function(e){e.preventDefault();finish();});
list.addEventListener('dragend',finish);
list.addEventListener('keydown',function(e){
var li=rowOf(e.target);
if(!li||e.altKey||e.ctrlKey||e.metaKey)return;
if(e.key==='ArrowUp'&&li.previousElementSibling){
list.insertBefore(li,li.previousElementSibling);}
else if(e.key==='ArrowDown'&&li.nextElementSibling){
list.insertBefore(li.nextElementSibling,li);}
else{return;}
e.preventDefault();
markDirty();
li.focus();});
})();
(function(){
function flash(btn){
btn.classList.add('copied');
window.setTimeout(function(){btn.classList.remove('copied');},1200);}
function legacy(name,btn){
var t=document.createElement('textarea');
t.value=name;t.setAttribute('readonly','');
t.style.position='fixed';t.style.left='-9999px';
document.body.appendChild(t);t.select();
try{document.execCommand('copy');flash(btn);}catch(err){}
document.body.removeChild(t);}
function copyName(name,btn){
if(!name)return;
if(navigator.clipboard&&navigator.clipboard.writeText){
navigator.clipboard.writeText(name).then(function(){flash(btn);})
.catch(function(){legacy(name,btn);});
return;}
legacy(name,btn);}
document.addEventListener('click',function(e){
var t=e.target;
while(t&&t!==document){
if(t.getAttribute&&t.classList&&t.classList.contains('copy-name')){
e.preventDefault();
copyName(t.getAttribute('data-copy-name')||'',t);
return;}
t=t.parentNode;}});
})();
(function(){
var body=document.body;
var pageNames=body.getAttribute('data-names');
var q=pageNames==='pseudonym'?'?names=pseudonym':'';
var url='/state'+q;
var pageHref='/'+q;
var lastGen=parseInt(body.getAttribute('data-generation'),10)||0;
var lastSeen=Date.now();
var pending=false;
var DASH='\\u2014';
function $(id){return document.getElementById(id);}
function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,function(c){
return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#x27;'}[c];});}
function tile(cls,k,v,extra){
return '<div class="tile'+(cls?' '+cls:'')+'"><span class="k">'+k+'</span>'
+'<b class="v'+(cls==='clock'||cls==='clock ours'?' who':'')+'"'
+(k==='Next pick'?' id="next-pick"':'')+'>'+esc(v)+'</b>'+(extra||'')+'</div>';}
function pagePhase(){
var p=body.getAttribute('data-phase');
return p==='disambiguating'?'drafting':p;}
function clockHtml(s){
var oc=s.on_the_clock||null;
var ours=!!(oc&&oc.ours);
var h=tile('','Next pick',(s.complete||s.upcoming==null)?DASH:s.upcoming)
+tile(ours?'clock ours':'clock','On the clock',oc?oc.label:DASH,
ours?'<span class="tag">us</span>':'')
+tile('','Our next',s.next_ours==null?DASH:s.next_ours);
if(s.complete){h+=tile('done','Status','Draft complete');}
else if(s.turn){h+=tile('turn','Status','TURN');}
if(s.phase!==pagePhase()){
h+='<a class="tile stale" href="'+esc(pageHref)+'">board changed '+DASH
+' refresh</a>';}
return h;}
function briefHtml(b){
var h='<div class="brief'+(b.absent?' absent':'')+'"><div class="brief-h">'
+'<strong>'+esc(b.persona)+'</strong>';
if(b.confidence!=null){
h+='<span class="conf">confidence '+esc(b.confidence)+'</span>';}
if(b.absent){h+='<span class="abs">absent</span>';}
h+='</div>';
if(b.reasoning){h+='<p>'+esc(b.reasoning)+'</p>';}
if(b.dissent){h+='<p class="dissent">Dissent: '+esc(b.dissent)+'</p>';}
return h+'</div>';}
function panelHtml(p){
var h='<div class="panel">';
if(p.decision){
h+='<h3>GM rationale</h3><p class="rationale">'+esc(p.decision.rationale)+'</p>';
var chips='';
(p.decision.adopted_from||[]).forEach(function(n){
chips+='<span class="chip">adopted: '+esc(n)+'</span>';});
(p.decision.overruled||[]).forEach(function(n){
chips+='<span class="chip over">overruled: '+esc(n)+'</span>';});
if(chips){h+='<p class="chips">'+chips+'</p>';}}
if(p.briefs&&p.briefs.length){
h+='<h3>Specialists</h3>';
p.briefs.forEach(function(b){h+=briefHtml(b);});}
return h+'</div>';}
function slateHtml(s){
var sl=s.slate;
var h='<section class="card slate"><div class="card-h"><h2>Council slate</h2>';
var running=s.council_running
?'<p class="running"><span class="dot"></span>council running\\u2026</p>':'';
if(!sl||!sl.items||!sl.items.length){
return h+'</div>'+running+'<p class="muted">No ranked list yet '+DASH
+' enter our slot, then wait one recompute.</p></section>';}
h+=sl.source==='fallback'
?'<span class="badge warn">tier fallback</span>'
:'<span class="badge ok">council</span>';
if(sl.failure_mode){h+='<span class="fail">'+esc(sl.failure_mode)+'</span>';}
h+='</div>'+running+'<ol class="slate-list">';
sl.items.forEach(function(it){
h+='<li><span class="rk">'+esc(it.rank)+'</span>'
+'<span class="nm">'+esc(it.name)+'</span>'
+'<span class="pt">'+esc(it.position)+' '+esc(it.team)+'</span>'
+'<button type="button" class="copy-name" data-copy-name="'+esc(it.name)+'"'
+' aria-label="Copy player name" title="Copy name">'
+'<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">'
+'<rect x="5" y="5" width="8" height="9" rx="1" fill="none"'
+' stroke="currentColor" stroke-width="1.4"/>'
+'<path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H10" fill="none"'
+' stroke="currentColor" stroke-width="1.4"/></svg></button>'
+'<code>'+esc(it.player_key)+'</code></li>';});
h+='</ol>';
var p=s.panel;
if(p&&p.packet_hash===sl.packet_hash){h+=panelHtml(p);}
return h+'</section>';}
function tick(){
var el=$('updated-ago');if(!el)return;
var secs=Math.floor((Date.now()-lastSeen)/1000);
el.textContent=secs<1?'updated just now':'updated '+secs+'s ago';}
function setDisconnected(on){var d=$('disconnected');if(d){d.hidden=!on;}}
function apply(s){
setDisconnected(false);
if(s.generation===lastGen){return;}
lastGen=s.generation;lastSeen=Date.now();
body.setAttribute('data-generation',String(s.generation));
var clock=$('clock-line');if(clock){clock.innerHTML=clockHtml(s);}
var slate=$('slate-region');if(slate){slate.innerHTML=slateHtml(s);}
tick();}
function poll(){
if(pending||typeof fetch!=='function')return;
pending=true;
fetch(url,{cache:'no-store',credentials:'same-origin'}).then(function(r){
if(!r.ok){throw new Error('status '+r.status);}
return r.json();})
.then(function(s){pending=false;apply(s);})
.catch(function(){pending=false;setDisconnected(true);});}
if(!$('updated-ago')&&!$('clock-line'))return;
setInterval(tick,1000);
setInterval(poll,1000);
poll();
})();
"""

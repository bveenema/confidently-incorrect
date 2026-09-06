"""Draft decision packet and packet_hash. No real manager names."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from data.league_settings import LeagueSettings
from data.pool import PooledPlayer, normalize_position
from draft.board import DraftBoard, RecordedPick
from draft.errors import DraftStateError
from draft.match import player_key

# Prompt-size cap, not a league-derived value. Models only need a board
# deep enough to rank 5; the full available pool is hundreds of rows.
COUNCIL_POOL_CAP = 100


def packet_hash(packet: dict[str, Any]) -> str:
    blob = json.dumps(packet, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_draft_strategy(root: Path) -> Any | None:
    """Optional strategy.json draft knob. Missing file is None, not a default."""
    path = root / "strategy.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DraftStateError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DraftStateError(f"{path} must contain a JSON object")
    if "draft_strategy" in raw:
        return raw["draft_strategy"]
    if "draft" in raw:
        return raw["draft"]
    return None


def council_pool_keys(available: Sequence[PooledPlayer]) -> list[str]:
    ranked = [p for p in available if p.value_rank is not None]
    ranked.sort(key=lambda p: p.value_rank or 0)
    rest = [p for p in available if p.value_rank is None]
    rest.sort(key=lambda p: (-_sort_points(p), p.name))
    chosen = (ranked + rest)[:COUNCIL_POOL_CAP]
    return [player_key(p) for p in chosen]


def build_draft_packet(
    board: DraftBoard,
    settings: LeagueSettings,
    available: Sequence[PooledPlayer],
    *,
    draft_strategy: Any | None = None,
) -> dict[str, Any]:
    clock = board.on_the_clock()
    ours = board.next_ours()
    packet: dict[str, Any] = {
        "decision_type": "draft",
        "team_count": settings.team_count,
        "rounds": settings.draft.rounds,
        "our_slot": board.our_slot,
        "upcoming": board.upcoming,
        "on_the_clock": clock,
        "next_ours": ours,
        "at_turn": board.turn(),
        "complete": board.complete,
        "picks_so_far": len(board.picks),
        "our_roster": [_roster_row(pick) for pick in board.our_roster()],
        "positional_scarcity": _scarcity(settings, board.our_roster(), available),
        "tier_breaks": [
            {
                "player_key": player_key(player),
                "name": player.name,
                "position": player.position,
                "tier": player.tier,
            }
            for player in available
            if player.tier_break_after
        ],
        "adp_vs_pick": [
            {
                "player_key": player_key(player),
                "name": player.name,
                "adp": player.adp,
                "value_rank": player.value_rank,
                "adp_delta": player.adp_delta,
                "upcoming": board.upcoming,
            }
            for player in _adp_slice(available)
        ],
    }
    if draft_strategy is not None:
        packet["draft_strategy"] = draft_strategy
    return packet


def _roster_row(pick: RecordedPick) -> dict[str, Any]:
    return {
        "player_key": pick.player_key,
        "name": pick.name,
        "position": pick.position,
        "team": pick.team,
        "overall": pick.overall,
    }


def _scarcity(
    settings: LeagueSettings,
    roster: Sequence[RecordedPick],
    available: Sequence[PooledPlayer],
) -> list[dict[str, Any]]:
    filled = Counter(
        normalize_position(pick.position) for pick in roster if pick.position
    )
    avail = Counter(normalize_position(player.position) for player in available)
    rows: list[dict[str, Any]] = []
    for slot in settings.roster_slots:
        pos = normalize_position(slot.position)
        if pos in {"BN", "BENCH", "IR"}:
            continue
        if pos in {"W/R/T", "WRT", "FLEX"}:
            have = _flex_filled(filled, slot.count, settings)
            open_count = avail.get("WR", 0) + avail.get("RB", 0) + avail.get("TE", 0)
        else:
            have = filled.get(pos, 0)
            open_count = avail.get(pos, 0)
        rows.append(
            {
                "slot": slot.position,
                "need": max(0, slot.count - have),
                "available": open_count,
            }
        )
    return rows


def _flex_filled(
    filled: Counter[str], flex_count: int, settings: LeagueSettings
) -> int:
    """Skill players beyond dedicated WR/RB/TE slots sit in flex."""
    extra = 0
    for slot in settings.roster_slots:
        pos = normalize_position(slot.position)
        if pos not in {"WR", "RB", "TE"}:
            continue
        extra += max(0, filled.get(pos, 0) - slot.count)
    return min(flex_count, extra)


def _adp_slice(available: Sequence[PooledPlayer]) -> list[PooledPlayer]:
    rows = [p for p in available if p.adp is not None]
    rows.sort(key=lambda p: (p.value_rank is None, p.value_rank or 0, p.adp or 0))
    return rows[:20]


def _sort_points(player: PooledPlayer) -> float:
    if isinstance(player.fp_points, (int, float)) and not isinstance(
        player.fp_points, bool
    ):
        return float(player.fp_points)
    return 0.0

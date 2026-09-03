"""In-memory draft board: picks, available pool, next pick, snake turn."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from data.pool import PooledPlayer
from draft.errors import DraftStateError
from draft.match import player_key
from draft.snake import (
    draft_length,
    is_snake_turn,
    next_our_overall,
    next_overall,
    slot_on_the_clock,
)


@dataclass(frozen=True)
class RecordedPick:
    overall: int
    slot: int
    kind: str
    ours: bool
    player_key: str | None = None
    name: str | None = None
    position: str | None = None
    team: str | None = None


@dataclass(frozen=True)
class DraftBoard:
    team_count: int
    rounds: int
    our_slot: int | None
    picks: tuple[RecordedPick, ...] = ()

    @property
    def upcoming(self) -> int:
        return next_overall(len(self.picks))

    @property
    def complete(self) -> bool:
        return len(self.picks) >= draft_length(self.team_count, self.rounds)

    def on_the_clock(self) -> int | None:
        if self.complete:
            return None
        return slot_on_the_clock(self.upcoming, self.team_count)

    def next_ours(self) -> int | None:
        if self.our_slot is None:
            return None
        return next_our_overall(
            self.upcoming, self.our_slot, self.team_count, self.rounds
        )

    def turn(self) -> bool:
        if self.our_slot is None or self.complete:
            return False
        return is_snake_turn(self.upcoming, self.our_slot, self.team_count, self.rounds)

    def drafted_keys(self) -> frozenset[str]:
        return frozenset(pick.player_key for pick in self.picks if pick.player_key)

    def available(self, players: Sequence[PooledPlayer]) -> tuple[PooledPlayer, ...]:
        taken = self.drafted_keys()
        return tuple(p for p in players if player_key(p) not in taken)

    def our_roster(self) -> tuple[RecordedPick, ...]:
        return tuple(pick for pick in self.picks if pick.ours and pick.kind == "player")


def new_board(team_count: int, rounds: int) -> DraftBoard:
    return DraftBoard(team_count=team_count, rounds=rounds, our_slot=None)


def set_our_slot(board: DraftBoard, our_slot: int) -> DraftBoard:
    if board.picks:
        raise DraftStateError("cannot change our slot after picks are recorded")
    if our_slot < 1 or our_slot > board.team_count:
        raise DraftStateError(
            f"our slot must be in 1..{board.team_count} (got {our_slot})"
        )
    return replace(board, our_slot=our_slot)


def sync_settings(board: DraftBoard, team_count: int, rounds: int) -> DraftBoard:
    """Re-read league settings. Fail loud if picks would be rebased."""
    if board.picks and (team_count != board.team_count or rounds != board.rounds):
        raise DraftStateError(
            "league-settings.json team_count or draft.rounds changed after "
            "picks were recorded. Fix the file or delete draft-board.json "
            "to start over."
        )
    if board.our_slot is not None and board.our_slot > team_count:
        raise DraftStateError(f"our slot {board.our_slot} is outside 1..{team_count}")
    return replace(board, team_count=team_count, rounds=rounds)


def record_player(board: DraftBoard, player: PooledPlayer) -> DraftBoard:
    _require_ready(board)
    key = player_key(player)
    if key in board.drafted_keys():
        raise DraftStateError(f"already drafted: {player.name}")
    overall = board.upcoming
    slot = slot_on_the_clock(overall, board.team_count)
    pick = RecordedPick(
        overall=overall,
        slot=slot,
        kind="player",
        ours=board.our_slot == slot,
        player_key=key,
        name=player.name,
        position=player.position,
        team=player.team,
    )
    return replace(board, picks=board.picks + (pick,))


def advance_unnamed(board: DraftBoard) -> DraftBoard:
    """Clock-only: someone else picked; do not remove a pool row."""
    _require_ready(board)
    overall = board.upcoming
    slot = slot_on_the_clock(overall, board.team_count)
    pick = RecordedPick(
        overall=overall,
        slot=slot,
        kind="unnamed",
        ours=board.our_slot == slot,
    )
    return replace(board, picks=board.picks + (pick,))


def undo_last(board: DraftBoard) -> DraftBoard:
    if not board.picks:
        raise DraftStateError("no picks to undo")
    return replace(board, picks=board.picks[:-1])


def _require_ready(board: DraftBoard) -> None:
    if board.our_slot is None:
        raise DraftStateError("set our draft slot before recording picks")
    if board.complete:
        raise DraftStateError("draft is complete")

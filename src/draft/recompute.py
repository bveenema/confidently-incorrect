"""Latest-only draft council recompute. Pick POST never waits (D-94)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from council.errors import CouncilError, CouncilRunError
from council.ledger import (
    ConsideredOption,
    ensure_ledger,
    ensure_season,
    insert_considered_options,
    insert_decision,
    insert_run,
    update_run,
)
from council.orchestrator import CouncilResult, run_council
from council.schema import GmAction, GmDecision
from data.league_settings import LeagueSettings
from data.pool import PooledPlayer
from draft.board import DraftBoard
from draft.fallback import tier_best_available
from draft.match import find_by_key, player_key
from draft.packet import (
    build_draft_packet,
    council_pool_keys,
    load_draft_strategy,
    packet_hash,
)
from notes.append import load_notes_text

FAILURE_MODEL = "model_failure"
FAILURE_SUPERSEDED = "superseded"
GM = "maddox"

CouncilRunner = Callable[..., CouncilResult]


@dataclass(frozen=True)
class SlateItem:
    rank: int
    player_key: str
    name: str
    position: str
    team: str


@dataclass(frozen=True)
class DraftSlate:
    packet_hash: str
    items: tuple[SlateItem, ...]
    source: str
    run_id: int | None
    failure_mode: str | None


class NullRecompute:
    """No council, no threads. Used by pick-entry tests that are not issue 12."""

    latest: DraftSlate | None = None

    def schedule(self, board: DraftBoard) -> None:
        return None

    def wait_idle(self, timeout: float = 5.0) -> None:
        return None


class DraftRecompute:
    def __init__(
        self,
        app: Any,
        *,
        runner: CouncilRunner | None = None,
    ) -> None:
        self._app = app
        self._runner = runner or _default_runner
        self._lock = threading.Lock()
        self._generation = 0
        self._threads: list[threading.Thread] = []
        self.latest: DraftSlate | None = None

    def schedule(self, board: DraftBoard) -> None:
        """Seed fallback immediately, then start a background council pass."""
        settings = self._app.settings()
        available = board.available(self._app.pool.players)
        strategy = load_draft_strategy(self._app.root)
        packet = build_draft_packet(
            board,
            settings,
            available,
            draft_strategy=strategy,
            notes=load_notes_text(self._app.root) or None,
        )
        digest = packet_hash(packet)
        fallback = tier_best_available(available)
        with self._lock:
            self._generation += 1
            gen = self._generation
            self.latest = _slate_from_players(
                digest, fallback, source="fallback", run_id=None, failure_mode=None
            )
        thread = threading.Thread(
            target=self._worker,
            args=(gen, board, settings, available, packet, digest, fallback),
            daemon=True,
            name=f"draft-recompute-{gen}",
        )
        self._threads.append(thread)
        thread.start()

    def wait_idle(self, timeout: float = 5.0) -> None:
        for thread in list(self._threads):
            thread.join(timeout)

    def _worker(
        self,
        gen: int,
        board: DraftBoard,
        settings: LeagueSettings,
        available: Sequence[PooledPlayer],
        packet: dict[str, Any],
        digest: str,
        fallback: tuple[PooledPlayer, ...],
    ) -> None:
        stale = not self._is_current(gen)
        try:
            if stale:
                run_id = self._write_superseded(digest)
                self._write_options(run_id, None, fallback)
                return
            result = self._runner(
                state_dir=self._app.root,
                packet=packet,
                pool=council_pool_keys(available),
                decision_type="draft",
                season_id=self._app.season_id,
                packet_hash=digest,
            )
            self._write_options(result.run_id, result, fallback)
            items = _items_from_decision(result, available)
            source = "council"
            failure: str | None = None
            run_id = result.run_id
        except CouncilRunError as exc:
            run_id = exc.run_id or self._write_failed_run(digest, exc.failure_mode)
            if exc.run_id is None:
                update_run(
                    self._app.root,
                    run_id,
                    failure_mode=exc.failure_mode or FAILURE_MODEL,
                )
            self._write_options(run_id, None, fallback)
            self._write_fallback_decision(run_id, fallback)
            items = _items_from_players(fallback)
            source = "fallback"
            failure = exc.failure_mode or FAILURE_MODEL
        except CouncilError:
            run_id = self._write_failed_run(digest, FAILURE_MODEL)
            self._write_options(run_id, None, fallback)
            self._write_fallback_decision(run_id, fallback)
            items = _items_from_players(fallback)
            source = "fallback"
            failure = FAILURE_MODEL
        except Exception:
            run_id = self._write_failed_run(digest, "internal_error")
            self._write_options(run_id, None, fallback)
            self._write_fallback_decision(run_id, fallback)
            items = _items_from_players(fallback)
            source = "fallback"
            failure = "internal_error"
        if not items:
            items = _items_from_players(fallback)
            source = "fallback"
        if not self._is_current(gen):
            return
        with self._lock:
            if self._generation != gen:
                return
            self.latest = DraftSlate(
                packet_hash=digest,
                items=items,
                source=source,
                run_id=run_id,
                failure_mode=failure,
            )

    def _is_current(self, gen: int) -> bool:
        with self._lock:
            return self._generation == gen

    def _write_superseded(self, digest: str) -> int:
        ensure_ledger(self._app.root)
        ensure_season(self._app.root, self._app.season_id)
        run_id = insert_run(
            self._app.root,
            season_id=self._app.season_id,
            decision_type="draft",
            packet_hash=digest,
        )
        update_run(self._app.root, run_id, failure_mode=FAILURE_SUPERSEDED)
        return run_id

    def _write_failed_run(self, digest: str, mode: str | None) -> int:
        ensure_ledger(self._app.root)
        ensure_season(self._app.root, self._app.season_id)
        run_id = insert_run(
            self._app.root,
            season_id=self._app.season_id,
            decision_type="draft",
            packet_hash=digest,
        )
        update_run(self._app.root, run_id, failure_mode=mode or FAILURE_MODEL)
        return run_id

    def _write_options(
        self,
        run_id: int,
        result: CouncilResult | None,
        fallback: Sequence[PooledPlayer],
    ) -> None:
        rows: list[ConsideredOption] = []
        if result is not None:
            for brief in result.briefs:
                for rec in brief.recommendations:
                    player = find_by_key(self._app.pool.players, rec.player_key)
                    rows.append(_option(brief.persona, rec.player_key, player))
            if result.decision is not None:
                for action in result.decision.final_actions:
                    player = find_by_key(self._app.pool.players, action.player_key)
                    rows.append(_option(GM, action.player_key, player))
        if not rows:
            for player in fallback:
                rows.append(_option(GM, player_key(player), player))
        if not rows:
            return
        insert_considered_options(self._app.root, run_id, rows)

    def _write_fallback_decision(
        self, run_id: int, fallback: Sequence[PooledPlayer]
    ) -> None:
        if not fallback:
            return
        decision = GmDecision(
            decision_type="draft",
            final_actions=tuple(
                GmAction(action="draft", player_key=player_key(p), slot=None)
                for p in fallback
            ),
            adopted_from=(),
            overruled=(),
            override_reason="tier-based best-available",
            unanimous_override=False,
            rationale="Model failure; falling through to precomputed tiers.",
            voice_line="Best available.",
        )
        insert_decision(self._app.root, run_id, decision)


def _default_runner(**kwargs: Any) -> CouncilResult:
    return run_council(**kwargs)


def _option(persona: str, key: str, player: PooledPlayer | None) -> ConsideredOption:
    return ConsideredOption(
        persona=persona,
        player_key=key,
        contemplated_action="draft",
        projection_primary=_num(player.fp_points if player else None),
        projection_secondary=_num(player.tank_points if player else None),
        projection_delta=_num(player.source_delta if player else None),
        std_dev=None,
        injury_status=None,
        chosen=0,
    )


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _items_from_decision(
    result: CouncilResult, available: Sequence[PooledPlayer]
) -> tuple[SlateItem, ...]:
    if result.decision is None:
        return ()
    items: list[SlateItem] = []
    for index, action in enumerate(result.decision.final_actions, start=1):
        player = find_by_key(available, action.player_key)
        items.append(
            SlateItem(
                rank=index,
                player_key=action.player_key,
                name=player.name if player else action.player_key,
                position=player.position if player else "",
                team=player.team if player else "",
            )
        )
    return tuple(items)


def _items_from_players(players: Sequence[PooledPlayer]) -> tuple[SlateItem, ...]:
    return tuple(
        SlateItem(
            rank=index,
            player_key=player_key(player),
            name=player.name,
            position=player.position,
            team=player.team,
        )
        for index, player in enumerate(players, start=1)
    )


def _slate_from_players(
    digest: str,
    players: Sequence[PooledPlayer],
    *,
    source: str,
    run_id: int | None,
    failure_mode: str | None,
) -> DraftSlate:
    return DraftSlate(
        packet_hash=digest,
        items=_items_from_players(players),
        source=source,
        run_id=run_id,
        failure_mode=failure_mode,
    )

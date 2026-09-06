"""Latest-only draft council recompute. Pick POST never waits (D-94)."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from council.errors import CouncilError, CouncilRunError
from council.ledger import (
    ConsideredOption,
    StoredDraftRun,
    ensure_ledger,
    ensure_season,
    insert_considered_options,
    insert_decision,
    insert_run,
    load_latest_draft_run,
    update_run,
)
from council.openrouter import OpenRouterClient
from council.orchestrator import CouncilResult, run_council
from council.schema import GmAction, GmDecision
from data.league_settings import LeagueSettings
from data.pool import PooledPlayer
from draft.board import DraftBoard, RecordedPick
from draft.fallback import MIN_SLATE, tier_best_available
from draft.match import find_by_key, player_key
from draft.need import accept_position, consume, starter_needs
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
DRAFT_DEADLINE_S = 38.0
DRAFT_HTTP_TIMEOUT_S = 15.0

CouncilRunner = Callable[..., CouncilResult]


def ours_on_the_clock(board: DraftBoard) -> bool:
    """True when the next overall pick is ours. Not the two-pick snake turn."""
    if board.complete or board.our_slot is None:
        return False
    return board.next_ours() == board.upcoming


def _keep_council(slate: DraftSlate | None) -> bool:
    """True when a readable panel should stay on the page (D-111)."""
    if slate is None or slate.panel is None:
        return False
    return slate.panel.decision is not None or bool(slate.panel.briefs)


@dataclass(frozen=True)
class SlateItem:
    rank: int
    player_key: str
    name: str
    position: str
    team: str


@dataclass(frozen=True)
class SlateBrief:
    persona: str
    confidence: float | None
    reasoning: str | None
    dissent: str | None
    absent: bool


@dataclass(frozen=True)
class SlateDecision:
    rationale: str
    adopted_from: tuple[str, ...]
    overruled: tuple[str, ...]
    final_actions: tuple[str, ...]


@dataclass(frozen=True)
class SlatePanel:
    packet_hash: str
    briefs: tuple[SlateBrief, ...]
    decision: SlateDecision | None


@dataclass(frozen=True)
class DraftSlate:
    packet_hash: str
    items: tuple[SlateItem, ...]
    source: str
    run_id: int | None
    failure_mode: str | None
    panel: SlatePanel | None = None


class NullRecompute:
    """No council, no threads. Used by pick-entry tests that are not issue 12."""

    latest: DraftSlate | None = None
    in_flight = False

    def schedule(self, board: DraftBoard) -> None:
        return None

    def recover(self, board: DraftBoard) -> None:
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
        self._deadline: threading.Timer | None = None
        self.latest: DraftSlate | None = None
        self.in_flight = False

    def schedule(self, board: DraftBoard) -> None:
        """Seed fallback immediately. Full panel only when we are on the clock."""
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
        fallback = tier_best_available(
            available, settings=settings, roster=board.our_roster()
        )
        ours = ours_on_the_clock(board)
        with self._lock:
            self._cancel_deadline_locked()
            self._generation += 1
            gen = self._generation
            prior = self.latest
            self.latest = _slate_from_players(
                digest,
                fallback,
                source="fallback",
                run_id=None,
                failure_mode=None,
                panel=_held_panel(prior, digest),
            )
            self.in_flight = ours
        self._app.bump()
        if not ours:
            return
        self._arm_deadline(gen)
        thread = threading.Thread(
            target=self._worker,
            args=(gen, board, settings, available, packet, digest, fallback, prior),
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
        prior: DraftSlate | None,
    ) -> None:
        stale = not self._is_current(gen)
        result: CouncilResult | None = None
        try:
            if stale:
                run_id = self._write_superseded(digest)
                self._write_options(run_id, None, fallback)
                return
            result = self._runner(
                state_dir=self._app.root,
                packet=packet,
                pool=council_pool_keys(available, settings, board.our_roster()),
                decision_type="draft",
                season_id=self._app.season_id,
                packet_hash=digest,
            )
            self._write_options(result.run_id, result, fallback)
            items = _items_from_decision(
                result, available, fallback, settings, board.our_roster()
            )
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
            self._cancel_deadline_locked()
            if failure and _keep_council(prior):
                self.in_flight = False
            else:
                panel = (
                    _panel_from_result(digest, result)
                    if result is not None
                    else _panel_from_fallback(digest)
                )
                self.latest = DraftSlate(
                    packet_hash=digest,
                    items=items,
                    source=source,
                    run_id=run_id,
                    failure_mode=failure,
                    panel=panel,
                )
                self.in_flight = False
        self._app.bump()

    def recover(self, board: DraftBoard) -> None:
        """Startup-only: attach the latest matching kb.db panel if latest is empty."""
        if self.latest is not None:
            return
        settings = self._app.settings()
        available = board.available(self._app.pool.players)
        packet = build_draft_packet(
            board,
            settings,
            available,
            draft_strategy=load_draft_strategy(self._app.root),
            notes=load_notes_text(self._app.root) or None,
        )
        digest = packet_hash(packet)
        stored = load_latest_draft_run(self._app.root, digest)
        if stored is None or stored.packet_hash != digest:
            self.schedule(board)
            return
        fallback = tier_best_available(
            available, settings=settings, roster=board.our_roster()
        )
        items = _items_from_stored(
            stored, available, fallback, settings, board.our_roster()
        ) or _items_from_players(fallback)
        source = (
            "council"
            if stored.decision is not None and not stored.failure_mode
            else "fallback"
        )
        self.latest = DraftSlate(
            packet_hash=digest,
            items=items,
            source=source,
            run_id=stored.run_id,
            failure_mode=stored.failure_mode,
            panel=_panel_from_stored(stored),
        )
        self._app.bump()
        if ours_on_the_clock(board) and stored.failure_mode:
            self.schedule(board)

    def _is_current(self, gen: int) -> bool:
        with self._lock:
            return self._generation == gen

    def _arm_deadline(self, gen: int) -> None:
        timer = threading.Timer(DRAFT_DEADLINE_S, self._expire, args=(gen,))
        timer.daemon = True
        with self._lock:
            if self._generation != gen:
                return
            self._cancel_deadline_locked()
            self._deadline = timer
        timer.start()

    def _expire(self, gen: int) -> None:
        with self._lock:
            if self._generation != gen:
                return
            self._generation += 1
            self.in_flight = False
            self._deadline = None
        self._app.bump()

    def _cancel_deadline_locked(self) -> None:
        timer = self._deadline
        self._deadline = None
        if timer is not None:
            timer.cancel()

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
    root = kwargs["state_dir"]
    client = OpenRouterClient(root, timeout=DRAFT_HTTP_TIMEOUT_S)
    try:
        return run_council(client=client, **kwargs)
    finally:
        client.close()


def _held_panel(prior: DraftSlate | None, digest: str) -> SlatePanel | None:
    """Copy a readable panel onto the current packet hash (D-111 / D-112)."""
    if prior is None or prior.panel is None:
        return None
    panel = prior.panel
    if panel.decision is None and not panel.briefs:
        return None
    return SlatePanel(
        packet_hash=digest,
        briefs=panel.briefs,
        decision=panel.decision,
    )


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
    result: CouncilResult,
    available: Sequence[PooledPlayer],
    fallback: Sequence[PooledPlayer],
    settings: LeagueSettings,
    roster: Sequence[RecordedPick],
) -> tuple[SlateItem, ...]:
    if result.decision is None:
        return ()
    chosen: list[PooledPlayer] = []
    for action in result.decision.final_actions:
        player = find_by_key(available, action.player_key)
        if player is not None:
            chosen.append(player)
    return _need_limited_items(chosen, fallback, settings, roster)


def _need_limited_items(
    chosen: Sequence[PooledPlayer],
    fallback: Sequence[PooledPlayer],
    settings: LeagueSettings,
    roster: Sequence[RecordedPick],
) -> tuple[SlateItem, ...]:
    needs = starter_needs(settings, roster)
    picked: list[PooledPlayer] = []
    seen: set[str] = set()
    for player in chosen:
        bucket = accept_position(player.position, needs)
        if bucket is None:
            continue
        consume(needs, bucket)
        picked.append(player)
        seen.add(player_key(player))
        if len(picked) >= MIN_SLATE:
            break
    if len(picked) < MIN_SLATE:
        for player in fallback:
            if len(picked) >= MIN_SLATE:
                break
            key = player_key(player)
            if key in seen:
                continue
            bucket = accept_position(player.position, needs)
            if bucket is None:
                continue
            consume(needs, bucket)
            picked.append(player)
            seen.add(key)
    return _items_from_players(picked)


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
    panel: SlatePanel | None = None,
) -> DraftSlate:
    return DraftSlate(
        packet_hash=digest,
        items=_items_from_players(players),
        source=source,
        run_id=run_id,
        failure_mode=failure_mode,
        panel=panel,
    )


def _panel_from_result(digest: str, result: CouncilResult) -> SlatePanel:
    absent = set(result.absent)
    briefs = tuple(
        SlateBrief(
            persona=brief.persona,
            confidence=brief.confidence,
            reasoning=brief.reasoning,
            dissent=brief.dissent,
            absent=brief.persona in absent,
        )
        for brief in result.briefs
    )
    decision = None
    if result.decision is not None:
        decision = SlateDecision(
            rationale=result.decision.rationale,
            adopted_from=result.decision.adopted_from,
            overruled=result.decision.overruled,
            final_actions=tuple(
                action.player_key for action in result.decision.final_actions
            ),
        )
    return SlatePanel(packet_hash=digest, briefs=briefs, decision=decision)


def _panel_from_fallback(digest: str) -> SlatePanel:
    return SlatePanel(
        packet_hash=digest,
        briefs=(),
        decision=SlateDecision(
            rationale="Model failure; falling through to precomputed tiers.",
            adopted_from=(),
            overruled=(),
            final_actions=(),
        ),
    )


def _panel_from_stored(stored: StoredDraftRun) -> SlatePanel:
    absent = set(stored.absent)
    briefs = tuple(
        SlateBrief(
            persona=brief.persona,
            confidence=brief.confidence,
            reasoning=brief.reasoning,
            dissent=brief.dissent,
            absent=brief.persona in absent,
        )
        for brief in stored.briefs
    )
    decision = None
    if stored.decision is not None:
        decision = SlateDecision(
            rationale=stored.decision.rationale,
            adopted_from=stored.decision.adopted_from,
            overruled=stored.decision.overruled,
            final_actions=tuple(
                str(item["player_key"])
                for item in stored.decision.final_actions
                if isinstance(item.get("player_key"), str)
            ),
        )
    return SlatePanel(packet_hash=stored.packet_hash, briefs=briefs, decision=decision)


def _items_from_stored(
    stored: StoredDraftRun,
    available: Sequence[PooledPlayer],
    fallback: Sequence[PooledPlayer],
    settings: LeagueSettings,
    roster: Sequence[RecordedPick],
) -> tuple[SlateItem, ...]:
    if stored.decision is None:
        return ()
    chosen: list[PooledPlayer] = []
    for action in stored.decision.final_actions:
        key = action.get("player_key")
        if not isinstance(key, str) or not key:
            continue
        player = find_by_key(available, key)
        if player is not None:
            chosen.append(player)
    return _need_limited_items(chosen, fallback, settings, roster)

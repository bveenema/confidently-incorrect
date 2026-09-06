"""JSON snapshot for GET /state. Display names never enter packets."""

from __future__ import annotations

from typing import Any

from draft.board import DraftBoard
from draft.recompute import DraftSlate, ours_on_the_clock
from draft.slots import SlotMap, display_for, pseudonym_for


def build_state(
    board: DraftBoard,
    *,
    mapping: SlotMap,
    slate: DraftSlate | None,
    generation: int,
    names: str = "display",
    candidates: bool = False,
    council_running: bool | None = None,
) -> dict[str, Any]:
    if board.our_slot is None:
        phase = "setup"
    elif board.complete:
        phase = "complete"
    elif candidates:
        phase = "disambiguating"
    else:
        phase = "drafting"
    clock = board.on_the_clock()
    on_clock: dict[str, Any] | None = None
    if clock is not None and phase != "setup":
        on_clock = {
            "slot": clock,
            "label": display_for(mapping, clock, names=names),
            "pseudonym": pseudonym_for(mapping, clock),
            "ours": board.our_slot == clock,
        }
    panel = None
    slate_payload = None
    if slate is not None and phase != "setup":
        slate_payload = {
            "packet_hash": slate.packet_hash,
            "source": slate.source,
            "failure_mode": slate.failure_mode,
            "run_id": slate.run_id,
            "items": [
                {
                    "rank": item.rank,
                    "player_key": item.player_key,
                    "name": item.name,
                    "position": item.position,
                    "team": item.team,
                }
                for item in slate.items
            ],
        }
        if slate.panel is not None and slate.panel.packet_hash == slate.packet_hash:
            panel = _panel_payload(slate)
    if council_running is None:
        council_running = (
            phase == "drafting"
            and ours_on_the_clock(board)
            and (slate is None or (slate.source == "fallback" and panel is None))
        )
    return {
        "generation": generation,
        "phase": phase,
        "upcoming": None if board.complete or phase == "setup" else board.upcoming,
        "on_the_clock": on_clock,
        "next_ours": board.next_ours() if phase != "setup" else None,
        "turn": board.turn() if phase != "setup" else False,
        "complete": board.complete,
        "slate": slate_payload,
        "panel": panel,
        "council_running": council_running,
    }


def _panel_payload(slate: DraftSlate) -> dict[str, Any] | None:
    panel = slate.panel
    if panel is None:
        return None
    decision = None
    if panel.decision is not None:
        decision = {
            "rationale": panel.decision.rationale,
            "adopted_from": list(panel.decision.adopted_from),
            "overruled": list(panel.decision.overruled),
            "final_actions": list(panel.decision.final_actions),
        }
    return {
        "packet_hash": panel.packet_hash,
        "briefs": [
            {
                "persona": brief.persona,
                "confidence": brief.confidence,
                "reasoning": brief.reasoning,
                "dissent": brief.dissent,
                "absent": brief.absent,
            }
            for brief in panel.briefs
        ],
        "decision": decision,
    }


def names_mode(raw: str) -> str:
    return "pseudonym" if raw.strip().lower() == "pseudonym" else "display"

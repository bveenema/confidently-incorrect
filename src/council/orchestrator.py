"""Parallel specialists, then the GM. Ledger writes are not optional."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from council.credentials import model_for
from council.errors import (
    CouncilAPIError,
    CouncilError,
    CouncilRunError,
    CouncilValidationError,
)
from council.ledger import (
    ensure_ledger,
    ensure_season,
    insert_brief_row,
    insert_decision,
    insert_run,
    update_run,
)
from council.openrouter import Completion, OpenRouterClient
from council.prompts import gm_system, specialist_system
from council.schema import (
    Brief,
    GmDecision,
    Recommendation,
    parse_json_object,
    validate_brief,
    validate_gm,
)

PANELS: dict[str, tuple[str, ...]] = {
    "draft": ("belichuk", "brand", "taco"),
    "lineup": ("belichuk", "brand", "taco"),
    "waiver": ("taco", "brand"),
    "trade": ("muskett", "brand", "belichuk"),
}
GM = "maddox"
FAILURE_GM_MISSING = "gm_missing"
FAILURE_GM_INVALID = "gm_invalid"


@dataclass(frozen=True)
class CouncilResult:
    run_id: int
    decision_type: str
    briefs: tuple[Brief, ...]
    rejected: tuple[str, ...]
    absent: tuple[str, ...]
    decision: GmDecision | None
    failure_mode: str | None


def run_council(
    *,
    state_dir: Path,
    packet: Mapping[str, Any],
    pool: Sequence[str],
    decision_type: str,
    season_id: str,
    client: OpenRouterClient | None = None,
    packet_hash: str | None = None,
) -> CouncilResult:
    """Run one council pass and write kb.db.

    A missing specialist is recorded and the run continues. A missing or
    invalid GM decision fails the run (failure_mode set, exception raised).
    Malformed briefs are rejected, not retried.
    """
    if decision_type not in PANELS:
        raise CouncilError(f"unknown decision_type {decision_type!r}")
    live_pool = {key.strip() for key in pool if isinstance(key, str) and key.strip()}
    if not live_pool:
        raise CouncilError("live player pool is empty")
    specialists = PANELS[decision_type]
    owned_client = client is None
    http = client or OpenRouterClient(state_dir)
    ensure_ledger(state_dir)
    ensure_season(state_dir, season_id)
    run_id = insert_run(
        state_dir,
        season_id=season_id,
        decision_type=decision_type,
        packet_hash=packet_hash,
    )
    try:
        return _execute(
            state_dir=state_dir,
            run_id=run_id,
            packet=dict(packet),
            pool=live_pool,
            decision_type=decision_type,
            specialists=specialists,
            client=http,
        )
    finally:
        if owned_client:
            http.close()


def _execute(
    *,
    state_dir: Path,
    run_id: int,
    packet: dict[str, Any],
    pool: set[str],
    decision_type: str,
    specialists: tuple[str, ...],
    client: OpenRouterClient,
) -> CouncilResult:
    user = _specialist_user(packet, pool, decision_type)
    valid: dict[str, Brief] = {}
    rejected: list[str] = []
    absent: list[str] = []

    with ThreadPoolExecutor(max_workers=len(specialists)) as workers:
        futures = {
            workers.submit(
                _specialist_call, client, persona, decision_type, user, pool
            ): persona
            for persona in specialists
        }
        for future in as_completed(futures):
            persona = futures[future]
            try:
                brief, rejection, completion = future.result()
            except Exception as exc:
                raise CouncilError(f"specialist {persona} crashed: {exc}") from exc
            if brief is not None or completion is not None:
                insert_brief_row(
                    state_dir,
                    run_id,
                    persona=persona,
                    brief=brief,
                    model=completion.model if completion else None,
                    tokens=completion.tokens if completion else None,
                    cost=completion.cost if completion else None,
                    rejection=rejection,
                )
            if brief is not None:
                valid[persona] = brief
            elif completion is not None:
                rejected.append(persona)
                absent.append(persona)
            else:
                absent.append(persona)

    update_run(state_dir, run_id, absent_personas=tuple(sorted(set(absent))))

    gm_user = _gm_user(packet, pool, decision_type, valid)
    decision, gm_brief, gm_rejection, gm_completion, gm_failure = _gm_call(
        client, decision_type, gm_user, pool
    )
    if gm_brief is not None or gm_completion is not None:
        insert_brief_row(
            state_dir,
            run_id,
            persona=GM,
            brief=gm_brief,
            model=gm_completion.model if gm_completion else None,
            tokens=gm_completion.tokens if gm_completion else None,
            cost=gm_completion.cost if gm_completion else None,
            rejection=gm_rejection,
        )
    if decision is None:
        mode = gm_failure or FAILURE_GM_MISSING
        update_run(state_dir, run_id, failure_mode=mode)
        raise CouncilRunError(f"run {run_id} failed: {mode}")
    insert_decision(state_dir, run_id, decision)
    return CouncilResult(
        run_id=run_id,
        decision_type=decision_type,
        briefs=tuple(valid[name] for name in specialists if name in valid),
        rejected=tuple(sorted(set(rejected))),
        absent=tuple(sorted(set(absent))),
        decision=decision,
        failure_mode=None,
    )


def _specialist_call(
    client: OpenRouterClient,
    persona: str,
    decision_type: str,
    user: str,
    pool: set[str],
) -> tuple[Brief | None, str | None, Completion | None]:
    try:
        completion = client.complete(
            model=model_for(persona, client.credentials),
            system=specialist_system(persona),
            user=user,
        )
    except (CouncilAPIError, CouncilError):
        return None, None, None
    try:
        raw = parse_json_object(completion.content)
        brief = validate_brief(
            raw,
            expected_persona=persona,
            decision_type=decision_type,
            pool=pool,
        )
    except CouncilValidationError as exc:
        return None, str(exc), completion
    return brief, None, completion


def _gm_call(
    client: OpenRouterClient,
    decision_type: str,
    user: str,
    pool: set[str],
) -> tuple[GmDecision | None, Brief | None, str | None, Completion | None, str | None]:
    try:
        completion = client.complete(
            model=model_for(GM, client.credentials),
            system=gm_system(),
            user=user,
        )
    except (CouncilAPIError, CouncilError):
        return None, None, None, None, FAILURE_GM_MISSING
    try:
        raw = parse_json_object(completion.content)
        decision = validate_gm(raw, decision_type=decision_type, pool=pool)
    except CouncilValidationError as exc:
        return None, None, str(exc), completion, FAILURE_GM_INVALID
    gm_brief = Brief(
        persona=GM,
        decision_type=decision.decision_type,
        recommendations=tuple(
            Recommendation(
                action=action.action,
                player_key=action.player_key,
                player_name="",
                slot=action.slot,
                priority=index + 1,
            )
            for index, action in enumerate(decision.final_actions)
        ),
        confidence=1.0,
        reasoning=decision.rationale,
        dissent=decision.override_reason,
        voice_line=decision.voice_line,
    )
    return decision, gm_brief, None, completion, None


def _specialist_user(packet: dict[str, Any], pool: set[str], decision_type: str) -> str:
    keys = "\n".join(f"- {key}" for key in sorted(pool))
    return (
        f"decision_type: {decision_type}\n\n"
        f"DECISION PACKET\n{json.dumps(packet, indent=2, sort_keys=True)}\n\n"
        f"VALID PLAYER KEYS\n{keys}\n"
    )


def _gm_user(
    packet: dict[str, Any],
    pool: set[str],
    decision_type: str,
    briefs: dict[str, Brief],
) -> str:
    payload = {
        persona: {
            "persona": brief.persona,
            "decision_type": brief.decision_type,
            "recommendations": [
                {
                    "action": rec.action,
                    "player_key": rec.player_key,
                    "player_name": rec.player_name,
                    "slot": rec.slot,
                    "priority": rec.priority,
                }
                for rec in brief.recommendations
            ],
            "confidence": brief.confidence,
            "reasoning": brief.reasoning,
            "dissent": brief.dissent,
            "voice_line": brief.voice_line,
        }
        for persona, brief in briefs.items()
    }
    keys = "\n".join(f"- {key}" for key in sorted(pool))
    return (
        f"decision_type: {decision_type}\n\n"
        f"DECISION PACKET\n{json.dumps(packet, indent=2, sort_keys=True)}\n\n"
        f"SPECIALIST BRIEFS\n{json.dumps(payload, indent=2, sort_keys=True)}\n\n"
        f"VALID PLAYER KEYS\n{keys}\n"
    )

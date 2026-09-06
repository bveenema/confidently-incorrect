"""Validate specialist briefs and GM decisions. Reject, do not retry."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from council.errors import CouncilValidationError

PERSONAS = frozenset({"belichuk", "brand", "taco", "muskett", "maddox", "lasso"})
DECISION_TYPES = frozenset({"lineup", "waiver", "trade", "draft"})
ACTIONS = frozenset(
    {
        "start",
        "bench",
        "add",
        "drop",
        "claim",
        "accept",
        "reject",
        "counter",
        "draft",
    }
)
DRAFT_MIN_RECS = 5
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True)
class Recommendation:
    action: str
    player_key: str
    player_name: str
    slot: str | None
    priority: int


@dataclass(frozen=True)
class Brief:
    persona: str
    decision_type: str
    recommendations: tuple[Recommendation, ...]
    confidence: float
    reasoning: str
    dissent: str | None
    voice_line: str


@dataclass(frozen=True)
class GmAction:
    action: str
    player_key: str
    slot: str | None


@dataclass(frozen=True)
class GmDecision:
    decision_type: str
    final_actions: tuple[GmAction, ...]
    adopted_from: tuple[str, ...]
    overruled: tuple[str, ...]
    override_reason: str | None
    unanimous_override: bool
    rationale: str
    voice_line: str


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object. Strip markdown fences. Do not retry a bad body."""
    if not isinstance(text, str) or not text.strip():
        raise CouncilValidationError("empty model output")
    blob = text.strip()
    fenced = _FENCE.match(blob)
    if fenced:
        blob = fenced.group(1).strip()
    try:
        raw = json.loads(blob)
    except json.JSONDecodeError:
        start = blob.find("{")
        end = blob.rfind("}")
        if start == -1 or end <= start:
            raise CouncilValidationError("model output is not a JSON object")
        try:
            raw = json.loads(blob[start : end + 1])
        except json.JSONDecodeError as exc:
            raise CouncilValidationError(
                f"model output is not valid JSON: {exc}"
            ) from exc
    if not isinstance(raw, dict):
        raise CouncilValidationError("model output must be a JSON object")
    return raw


def canonicalize_player_key(raw: str, pool: set[str]) -> str | None:
    """Return the pool key for a model-emitted id, or None if unknown.

    Accepts the exact pool key, a bare Yahoo player id, or a Yahoo API
    `{game}.p.{id}` string. The game id is not hardcoded.
    """
    key = raw.strip()
    if not key:
        return None
    if key in pool:
        return key
    yahoo_id = key.rsplit(".p.", 1)[-1] if ".p." in key else key
    aliased = f"yahoo:{yahoo_id}"
    if aliased in pool:
        return aliased
    return None


def validate_brief(
    raw: dict[str, Any],
    *,
    expected_persona: str,
    decision_type: str,
    pool: set[str],
) -> Brief:
    persona = _require_str(raw, "persona")
    if persona != expected_persona:
        raise CouncilValidationError(
            f"brief persona {persona!r} does not match {expected_persona}"
        )
    if persona not in PERSONAS:
        raise CouncilValidationError(f"unknown persona {persona!r}")
    dtype = _require_str(raw, "decision_type")
    if dtype != decision_type:
        raise CouncilValidationError(
            f"brief decision_type {dtype!r} does not match {decision_type}"
        )
    if dtype not in DECISION_TYPES:
        raise CouncilValidationError(f"unknown decision_type {dtype!r}")
    recs_raw = raw.get("recommendations")
    if not isinstance(recs_raw, list) or not recs_raw:
        raise CouncilValidationError("recommendations must be a non-empty array")
    recs = tuple(_recommendation(item, pool, i) for i, item in enumerate(recs_raw))
    if dtype == "draft" and len(recs) < DRAFT_MIN_RECS:
        raise CouncilValidationError(
            f"draft brief must rank at least {DRAFT_MIN_RECS} players, got {len(recs)}"
        )
    confidence = _confidence(raw.get("confidence"))
    reasoning = _require_str(raw, "reasoning")
    dissent = _optional_str(raw.get("dissent"))
    voice_line = _require_str(raw, "voice_line")
    return Brief(
        persona=persona,
        decision_type=dtype,
        recommendations=recs,
        confidence=confidence,
        reasoning=reasoning,
        dissent=dissent,
        voice_line=voice_line,
    )


def validate_gm(
    raw: dict[str, Any],
    *,
    decision_type: str,
    pool: set[str],
) -> GmDecision:
    dtype = _require_str(raw, "decision_type")
    if dtype != decision_type:
        raise CouncilValidationError(
            f"gm decision_type {dtype!r} does not match {decision_type}"
        )
    actions_raw = raw.get("final_actions")
    if not isinstance(actions_raw, list) or not actions_raw:
        raise CouncilValidationError("final_actions must be a non-empty array")
    actions = tuple(_gm_action(item, pool, i) for i, item in enumerate(actions_raw))
    if dtype == "draft" and len(actions) < DRAFT_MIN_RECS:
        raise CouncilValidationError(
            f"draft GM decision must rank at least {DRAFT_MIN_RECS} players, "
            f"got {len(actions)}"
        )
    adopted = _name_list(raw.get("adopted_from"), "adopted_from")
    overruled = _name_list(raw.get("overruled"), "overruled")
    override_reason = _optional_str(raw.get("override_reason"))
    unanimous = raw.get("unanimous_override")
    if not isinstance(unanimous, bool):
        raise CouncilValidationError("unanimous_override must be a boolean")
    return GmDecision(
        decision_type=dtype,
        final_actions=actions,
        adopted_from=adopted,
        overruled=overruled,
        override_reason=override_reason,
        unanimous_override=unanimous,
        rationale=_require_str(raw, "rationale"),
        voice_line=_require_str(raw, "voice_line"),
    )


def _recommendation(item: Any, pool: set[str], index: int) -> Recommendation:
    if not isinstance(item, dict):
        raise CouncilValidationError(f"recommendations[{index}] must be an object")
    action = item.get("action")
    if action not in ACTIONS:
        raise CouncilValidationError(f"recommendations[{index}].action is invalid")
    raw_key = item.get("player_key")
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise CouncilValidationError(f"recommendations[{index}].player_key is required")
    key = canonicalize_player_key(raw_key, pool)
    if key is None:
        raise CouncilValidationError(
            f"recommendations[{index}].player_key {raw_key!r} is unknown"
        )
    name = item.get("player_name")
    if not isinstance(name, str) or not name.strip():
        raise CouncilValidationError(
            f"recommendations[{index}].player_name is required"
        )
    slot = _optional_str(item.get("slot"))
    priority = item.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise CouncilValidationError(
            f"recommendations[{index}].priority must be an integer"
        )
    return Recommendation(
        action=str(action),
        player_key=key,
        player_name=name.strip(),
        slot=slot,
        priority=priority,
    )


def _gm_action(item: Any, pool: set[str], index: int) -> GmAction:
    if not isinstance(item, dict):
        raise CouncilValidationError(f"final_actions[{index}] must be an object")
    action = item.get("action")
    if action not in ACTIONS:
        raise CouncilValidationError(f"final_actions[{index}].action is invalid")
    raw_key = item.get("player_key")
    if not isinstance(raw_key, str) or not raw_key.strip():
        raise CouncilValidationError(f"final_actions[{index}].player_key is required")
    key = canonicalize_player_key(raw_key, pool)
    if key is None:
        raise CouncilValidationError(
            f"final_actions[{index}].player_key {raw_key!r} is not in the live pool"
        )
    return GmAction(
        action=str(action),
        player_key=key,
        slot=_optional_str(item.get("slot")),
    )


def _require_str(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CouncilValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CouncilValidationError("optional string field is not a string")
    stripped = value.strip()
    return stripped or None


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CouncilValidationError("confidence must be a number between 0 and 1")
    number = float(value)
    if number < 0.0 or number > 1.0:
        raise CouncilValidationError("confidence must be a number between 0 and 1")
    return number


def _name_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CouncilValidationError(f"{field} must be an array")
    names: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CouncilValidationError(f"{field} entries must be non-empty strings")
        name = item.strip()
        if name not in PERSONAS:
            raise CouncilValidationError(f"{field} has unknown persona {name!r}")
        names.append(name)
    return tuple(names)

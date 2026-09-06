"""Write council runs, briefs, and decisions to kb.db."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from council.errors import CouncilError
from council.schema import Brief, GmDecision, Recommendation
from db.errors import DbError
from db.ledger import connect, migrate

ET = ZoneInfo("America/New_York")


def now_et() -> str:
    return datetime.now(ET).isoformat(timespec="seconds")


def ensure_ledger(root: Path) -> Path:
    return migrate(root)


def ensure_season(root: Path, season_id: str) -> None:
    try:
        with connect(root) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seasons (season_id) VALUES (?)",
                (season_id,),
            )
            conn.commit()
    except DbError:
        raise
    except Exception as exc:
        raise CouncilError(f"failed to ensure season {season_id}: {exc}") from exc


def insert_run(
    root: Path,
    *,
    season_id: str,
    decision_type: str,
    ts: str | None = None,
    packet_hash: str | None = None,
) -> int:
    try:
        with connect(root) as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (season_id, ts, decision_type, packet_hash)
                VALUES (?, ?, ?, ?)
                """,
                (season_id, ts or now_et(), decision_type, packet_hash),
            )
            conn.commit()
            run_id = cur.lastrowid
    except DbError:
        raise
    except Exception as exc:
        raise CouncilError(f"failed to insert run: {exc}") from exc
    if not run_id:
        raise CouncilError("failed to insert run: no row id")
    return int(run_id)


def update_run(
    root: Path,
    run_id: int,
    *,
    failure_mode: str | None = None,
    absent_personas: Sequence[str] | None = None,
) -> None:
    fields: list[str] = []
    values: list[object] = []
    if failure_mode is not None:
        fields.append("failure_mode = ?")
        values.append(failure_mode)
    if absent_personas is not None:
        fields.append("absent_personas = ?")
        values.append(",".join(absent_personas))
    if not fields:
        return
    values.append(run_id)
    try:
        with connect(root) as conn:
            conn.execute(
                f"UPDATE runs SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            conn.commit()
    except DbError:
        raise
    except Exception as exc:
        raise CouncilError(f"failed to update run {run_id}: {exc}") from exc


def insert_brief_row(
    root: Path,
    run_id: int,
    *,
    persona: str,
    brief: Brief | None,
    model: str | None,
    tokens: int | None,
    cost: float | None,
    rejection: str | None = None,
) -> None:
    recommendations: str | None = None
    confidence: float | None = None
    reasoning: str | None = rejection
    dissent: str | None = None
    voice_line: str | None = None
    if brief is not None:
        recommendations = json.dumps(
            [_rec_json(rec) for rec in brief.recommendations],
            separators=(",", ":"),
        )
        confidence = brief.confidence
        reasoning = brief.reasoning
        dissent = brief.dissent
        voice_line = brief.voice_line
    try:
        with connect(root) as conn:
            conn.execute(
                """
                INSERT INTO briefs (
                    run_id, persona, recommendations, confidence, reasoning,
                    dissent, voice_line, model, tokens, cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    persona,
                    recommendations,
                    confidence,
                    reasoning,
                    dissent,
                    voice_line,
                    model,
                    tokens,
                    cost,
                ),
            )
            conn.commit()
    except DbError:
        raise
    except Exception as exc:
        raise CouncilError(f"failed to insert brief for {persona}: {exc}") from exc


def insert_decision(root: Path, run_id: int, decision: GmDecision) -> None:
    try:
        with connect(root) as conn:
            conn.execute(
                """
                INSERT INTO decisions (
                    run_id, final_actions, adopted_from, overruled,
                    override_reason, unanimous_override, rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    json.dumps(
                        [
                            {
                                "action": action.action,
                                "player_key": action.player_key,
                                "slot": action.slot,
                            }
                            for action in decision.final_actions
                        ],
                        separators=(",", ":"),
                    ),
                    json.dumps(list(decision.adopted_from), separators=(",", ":")),
                    json.dumps(list(decision.overruled), separators=(",", ":")),
                    decision.override_reason,
                    1 if decision.unanimous_override else 0,
                    decision.rationale,
                ),
            )
            conn.commit()
    except DbError:
        raise
    except Exception as exc:
        raise CouncilError(f"failed to insert decision: {exc}") from exc


def _rec_json(rec: Recommendation) -> dict[str, object]:
    return {
        "action": rec.action,
        "player_key": rec.player_key,
        "player_name": rec.player_name,
        "slot": rec.slot,
        "priority": rec.priority,
    }

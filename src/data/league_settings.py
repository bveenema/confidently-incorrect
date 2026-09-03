"""Load league settings from $CI_STATE_DIR/league-settings.json.

Nothing league-derived is a constant here. Missing or invalid files fail
loudly; there are no silent defaults that look like a real league.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, TypeGuard

from data.errors import LeagueSettingsError

_FILENAME = "league-settings.json"
_LINUX_DEFAULT = Path("/srv/ci")
_SCHEMA_VERSION = 1
_TEMPLATE_HINT = (
    "Copy templates/league-settings.json to $CI_STATE_DIR/league-settings.json "
    "and replace every fake value from the Yahoo league settings page."
)


@dataclass(frozen=True)
class RosterSlot:
    position: str
    count: int


@dataclass(frozen=True)
class ScoringCategory:
    stat: str
    points: float
    per: float | None = None
    bounds: tuple[int, int] | None = None


@dataclass(frozen=True)
class Scoring:
    fractional_points: bool
    negative_points: str
    categories: tuple[ScoringCategory, ...]


@dataclass(frozen=True)
class WaiverRules:
    type: str
    days: int
    process: str


@dataclass(frozen=True)
class PlayoffSettings:
    teams: int
    weeks: tuple[int, ...]


@dataclass(frozen=True)
class DraftSettings:
    rounds: int
    type: str


@dataclass(frozen=True)
class TradeReview:
    votes_to_veto: int
    days: int


@dataclass(frozen=True)
class LeagueSettings:
    schema_version: int
    team_count: int
    roster_slots: tuple[RosterSlot, ...]
    scoring: Scoring
    trade_deadline: date
    waiver: WaiverRules
    playoff: PlayoffSettings
    draft: DraftSettings
    trade_review: TradeReview | None
    max_acquisitions: int | None
    draft_pick_trades: bool | None
    ir_adds_from_waivers: bool | None
    source_path: Path


def state_dir(override: Path | None = None) -> Path:
    """Return CI_STATE_DIR, or /srv/ci when that directory exists."""
    if override is not None:
        return override
    raw = os.environ.get("CI_STATE_DIR")
    if raw:
        return Path(raw)
    if _LINUX_DEFAULT.is_dir():
        return _LINUX_DEFAULT
    raise LeagueSettingsError(
        "CI_STATE_DIR is not set and /srv/ci does not exist. "
        "Set CI_STATE_DIR to a directory outside the git worktree. " + _TEMPLATE_HINT
    )


def settings_path(root: Path | None = None) -> Path:
    return state_dir(root) / _FILENAME


def load_league_settings(root: Path | None = None) -> LeagueSettings:
    """Read and validate league settings. `root` is CI_STATE_DIR in tests."""
    return load_league_settings_file(settings_path(root))


def load_league_settings_file(path: Path) -> LeagueSettings:
    try:
        # utf-8-sig: Windows editors / PowerShell often write a BOM.
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise LeagueSettingsError(f"missing file: {path}. {_TEMPLATE_HINT}") from exc
    except json.JSONDecodeError as exc:
        raise LeagueSettingsError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise LeagueSettingsError(f"{path} must contain a JSON object")
    return _parse(raw, path)


def _parse(raw: dict[str, Any], path: Path) -> LeagueSettings:
    errors: list[str] = []

    version = raw.get("schema_version")
    if not _is_int(version):
        errors.append("schema_version must be an integer")
    elif version != _SCHEMA_VERSION:
        errors.append(
            f"unsupported schema_version {version} (expected {_SCHEMA_VERSION})"
        )

    team_count = raw.get("team_count")
    if not _is_int(team_count) or team_count < 1:
        errors.append("team_count must be an integer >= 1")

    slots = _parse_roster(raw.get("roster_slots"), errors)
    scoring = _parse_scoring(raw.get("scoring"), errors)
    deadline = _parse_deadline(raw.get("trade_deadline"), errors)
    waiver = _parse_waiver(raw.get("waiver"), errors)
    playoff = _parse_playoff(raw.get("playoff"), errors)
    draft = _parse_draft(raw.get("draft"), errors)
    review = _parse_trade_review(raw.get("trade_review"), errors)
    max_acq = _parse_optional_int(
        raw, "max_acquisitions", errors, allow_null=True, minimum=0
    )
    draft_pick_trades = _parse_optional_bool(raw, "draft_pick_trades", errors)
    ir_adds = _parse_optional_bool(raw, "ir_adds_from_waivers", errors)

    if errors:
        listing = "\n".join(f"  - {item}" for item in errors)
        raise LeagueSettingsError(f"{path} is invalid:\n{listing}")

    assert isinstance(version, int)
    assert isinstance(team_count, int)
    assert slots is not None
    assert scoring is not None
    assert deadline is not None
    assert waiver is not None
    assert playoff is not None
    assert draft is not None

    return LeagueSettings(
        schema_version=version,
        team_count=team_count,
        roster_slots=slots,
        scoring=scoring,
        trade_deadline=deadline,
        waiver=waiver,
        playoff=playoff,
        draft=draft,
        trade_review=review,
        max_acquisitions=max_acq,
        draft_pick_trades=draft_pick_trades,
        ir_adds_from_waivers=ir_adds,
        source_path=path,
    )


def _parse_roster(value: Any, errors: list[str]) -> tuple[RosterSlot, ...] | None:
    if not isinstance(value, list) or not value:
        errors.append("roster_slots must be a non-empty array")
        return None
    slots: list[RosterSlot] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        prefix = f"roster_slots[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        position = item.get("position")
        count = item.get("count")
        if not _is_nonempty_str(position):
            errors.append(f"{prefix}.position must be a non-empty string")
            position = None
        elif position in seen:
            errors.append(f"{prefix}.position {position!r} is duplicated")
            position = None
        else:
            seen.add(position)
        if not _is_int(count) or count < 1:
            errors.append(f"{prefix}.count must be an integer >= 1")
            continue
        if position is not None:
            slots.append(RosterSlot(position=position, count=count))
    return tuple(slots) if slots and len(slots) == len(value) else None


def _parse_scoring(value: Any, errors: list[str]) -> Scoring | None:
    if not isinstance(value, dict):
        errors.append("scoring must be an object")
        return None
    fractional = value.get("fractional_points")
    if not isinstance(fractional, bool):
        errors.append("scoring.fractional_points must be a boolean")
        fractional = None
    negative = value.get("negative_points")
    if not _is_nonempty_str(negative):
        errors.append("scoring.negative_points must be a non-empty string")
        negative = None
    raw_cats = value.get("categories")
    if not isinstance(raw_cats, list) or not raw_cats:
        errors.append("scoring.categories must be a non-empty array")
        return None
    categories: list[ScoringCategory] = []
    for index, item in enumerate(raw_cats):
        parsed = _parse_category(item, index, errors)
        if parsed is not None:
            categories.append(parsed)
    if fractional is None or negative is None or len(categories) != len(raw_cats):
        return None
    return Scoring(
        fractional_points=fractional,
        negative_points=negative,
        categories=tuple(categories),
    )


def _parse_category(item: Any, index: int, errors: list[str]) -> ScoringCategory | None:
    prefix = f"scoring.categories[{index}]"
    if not isinstance(item, dict):
        errors.append(f"{prefix} must be an object")
        return None
    stat = item.get("stat")
    points = item.get("points")
    ok = True
    if not _is_nonempty_str(stat):
        errors.append(f"{prefix}.stat must be a non-empty string")
        ok = False
    if not _is_number(points):
        errors.append(f"{prefix}.points must be a number")
        ok = False
    per: float | None = None
    if "per" in item:
        raw_per = item["per"]
        if not _is_number(raw_per) or raw_per <= 0:
            errors.append(f"{prefix}.per must be a number > 0")
            ok = False
        else:
            per = float(raw_per)
    bounds: tuple[int, int] | None = None
    if "range" in item:
        raw_range = item["range"]
        if (
            not isinstance(raw_range, list)
            or len(raw_range) != 2
            or not _is_int(raw_range[0])
            or not _is_int(raw_range[1])
            or raw_range[0] > raw_range[1]
        ):
            errors.append(f"{prefix}.range must be [min, max] integers with min <= max")
            ok = False
        else:
            bounds = (raw_range[0], raw_range[1])
    if per is not None and bounds is not None:
        errors.append(f"{prefix} cannot set both per and range")
        ok = False
    if not ok:
        return None
    assert isinstance(stat, str)
    assert _is_number(points)
    return ScoringCategory(stat=stat, points=float(points), per=per, bounds=bounds)


def _parse_deadline(value: Any, errors: list[str]) -> date | None:
    if not _is_nonempty_str(value):
        errors.append("trade_deadline must be a YYYY-MM-DD string")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append("trade_deadline must be a YYYY-MM-DD string")
        return None


def _parse_waiver(value: Any, errors: list[str]) -> WaiverRules | None:
    if not isinstance(value, dict):
        errors.append("waiver must be an object")
        return None
    wtype = value.get("type")
    days = value.get("days")
    process = value.get("process")
    ok = True
    if not _is_nonempty_str(wtype):
        errors.append("waiver.type must be a non-empty string")
        ok = False
    if not _is_int(days) or days < 0:
        errors.append("waiver.days must be an integer >= 0")
        ok = False
    if not _is_nonempty_str(process):
        errors.append("waiver.process must be a non-empty string")
        ok = False
    if not ok:
        return None
    assert isinstance(wtype, str)
    assert isinstance(days, int)
    assert isinstance(process, str)
    return WaiverRules(type=wtype, days=days, process=process)


def _parse_playoff(value: Any, errors: list[str]) -> PlayoffSettings | None:
    if not isinstance(value, dict):
        errors.append("playoff must be an object")
        return None
    teams = value.get("teams")
    weeks = value.get("weeks")
    ok = True
    if not _is_int(teams) or teams < 1:
        errors.append("playoff.teams must be an integer >= 1")
        ok = False
    if not isinstance(weeks, list) or not weeks:
        errors.append("playoff.weeks must be a non-empty array of integers")
        return None
    parsed_weeks: list[int] = []
    for index, week in enumerate(weeks):
        if not _is_int(week) or week < 1:
            errors.append(f"playoff.weeks[{index}] must be an integer >= 1")
            ok = False
        else:
            parsed_weeks.append(week)
    if not ok:
        return None
    assert isinstance(teams, int)
    return PlayoffSettings(teams=teams, weeks=tuple(parsed_weeks))


def _parse_draft(value: Any, errors: list[str]) -> DraftSettings | None:
    if not isinstance(value, dict):
        errors.append("draft must be an object")
        return None
    rounds = value.get("rounds")
    dtype = value.get("type")
    ok = True
    if not _is_int(rounds) or rounds < 1:
        errors.append("draft.rounds must be an integer >= 1")
        ok = False
    if not _is_nonempty_str(dtype):
        errors.append("draft.type must be a non-empty string")
        ok = False
    if not ok:
        return None
    assert isinstance(rounds, int)
    assert isinstance(dtype, str)
    return DraftSettings(rounds=rounds, type=dtype)


def _parse_trade_review(value: Any, errors: list[str]) -> TradeReview | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        errors.append("trade_review must be an object")
        return None
    votes = value.get("votes_to_veto")
    days = value.get("days")
    ok = True
    if not _is_int(votes) or votes < 1:
        errors.append("trade_review.votes_to_veto must be an integer >= 1")
        ok = False
    if not _is_int(days) or days < 0:
        errors.append("trade_review.days must be an integer >= 0")
        ok = False
    if not ok:
        return None
    assert _is_int(votes)
    assert _is_int(days)
    return TradeReview(votes_to_veto=votes, days=days)


def _parse_optional_int(
    raw: dict[str, Any],
    key: str,
    errors: list[str],
    *,
    allow_null: bool,
    minimum: int,
) -> int | None:
    if key not in raw:
        return None
    value = raw[key]
    if allow_null and value is None:
        return None
    if not _is_int(value) or value < minimum:
        errors.append(f"{key} must be an integer >= {minimum} or null")
        return None
    return value


def _parse_optional_bool(
    raw: dict[str, Any], key: str, errors: list[str]
) -> bool | None:
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, bool):
        errors.append(f"{key} must be a boolean")
        return None
    return value


def _is_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())

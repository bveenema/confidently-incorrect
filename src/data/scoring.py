"""Convert a raw stat line into league fantasy points.

Every number comes from the ingested scoring table. This module never
hardcodes league-derived values and never reads a provider point total.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from data.errors import DataError
from data.league_settings import Scoring, ScoringCategory


def fantasy_points(scoring: Scoring, stats: Mapping[str, Any]) -> int | float:
    """Apply `scoring.categories` to `stats` (slug → amount).

    Missing slugs are zero for count and rate categories. Band
    categories do not treat a missing slug as 0 — a QB line must not
    collect a DST shutout. An explicit 0 does match a `[0, 0]` band.
    Unknown keys, including any provider precomputed total, are
    ignored. Kicker distances must already be binned into slugs
    (`fg_0_19`, `fg_miss_40_49`, …).

    A-6 is unresolved: signed category `points` apply as written. The
    total is not floored at zero and penalty categories are not stripped.
    """
    total = 0.0
    for category in scoring.categories:
        total += _category_points(category, stats, scoring.fractional_points)
    if scoring.fractional_points:
        return total
    return _round_half_away(total)


def _category_points(
    category: ScoringCategory,
    stats: Mapping[str, Any],
    fractional_points: bool,
) -> float:
    value = _stat_value(stats, category.stat)
    if category.bounds is not None:
        if value is None:
            return 0.0
        low, high = category.bounds
        return category.points if low <= value <= high else 0.0
    amount = 0.0 if value is None else value
    if category.per is not None:
        if fractional_points:
            return category.points * (amount / category.per)
        return category.points * math.trunc(amount / category.per)
    return category.points * amount


def _stat_value(stats: Mapping[str, Any], slug: str) -> float | None:
    if slug not in stats or stats[slug] is None:
        return None
    raw = stats[slug]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise DataError(f"stat {slug!r} must be a number, got {type(raw).__name__}")
    value = float(raw)
    if not math.isfinite(value):
        raise DataError(f"stat {slug!r} must be finite, got {raw}")
    return value


def _round_half_away(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))

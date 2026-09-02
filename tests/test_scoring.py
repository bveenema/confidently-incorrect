"""Scoring engine: stat line → league points.

League-like numbers live only in this fixture. Production code reads
them from the ingested table.
"""

from __future__ import annotations

import math

import pytest

from data import DataError, fantasy_points
from data.league_settings import Scoring, ScoringCategory

# Distinctive fixture values so each slug's contribution is identifiable.
# Not the production table — the engine must not contain these constants.
_KICKER_POINTS = {
    "fg_0_19": 3,
    "fg_20_29": 3,
    "fg_30_39": 3,
    "fg_40_49": 4,
    "fg_50_59": 5,
    "fg_60_plus": 6,
    "fg_miss_0_19": -4,
    "fg_miss_20_29": -3,
    "fg_miss_30_39": -3,
    "fg_miss_40_49": -2,
    "fg_miss_50_59": -1,
    "fg_miss_60_plus": -1,
    "pat_made": 1,
    "pat_miss": -1,
}

_DST_BANDS = (
    ScoringCategory("dst_pts_allowed", 10, bounds=(0, 0)),
    ScoringCategory("dst_pts_allowed", 7, bounds=(1, 6)),
    ScoringCategory("dst_pts_allowed", 4, bounds=(7, 13)),
    ScoringCategory("dst_pts_allowed", 1, bounds=(14, 20)),
    ScoringCategory("dst_pts_allowed", 0, bounds=(21, 27)),
    ScoringCategory("dst_pts_allowed", -1, bounds=(28, 34)),
    ScoringCategory("dst_pts_allowed", -4, bounds=(35, 99)),
    ScoringCategory("dst_yds_allowed", 10, bounds=(0, 99)),
    ScoringCategory("dst_yds_allowed", 5, bounds=(100, 199)),
    ScoringCategory("dst_yds_allowed", 0, bounds=(200, 299)),
    ScoringCategory("dst_yds_allowed", -3, bounds=(300, 399)),
    ScoringCategory("dst_yds_allowed", -5, bounds=(400, 999)),
)


def _cat(
    stat: str,
    points: float,
    *,
    per: float | None = None,
    bounds: tuple[int, int] | None = None,
) -> ScoringCategory:
    return ScoringCategory(stat=stat, points=points, per=per, bounds=bounds)


def _table(
    categories: tuple[ScoringCategory, ...] | list[ScoringCategory],
    *,
    fractional: bool = False,
    negative: str = "example-unresolved",
) -> Scoring:
    return Scoring(
        fractional_points=fractional,
        negative_points=negative,
        categories=tuple(categories),
    )


def _league_like(*, fractional: bool = False) -> Scoring:
    """Fixture shaped like §0.1 plus the remaining template slugs."""
    return _table(
        [
            _cat("pass_cmp", 1),
            _cat("pass_att", 0),
            _cat("pass_yd", 1, per=15),
            _cat("pass_td", 6),
            _cat("pass_int", -1),
            _cat("rush_att", 0),
            _cat("rush_yd", 1, per=10),
            _cat("rush_td", 6),
            _cat("rec", 1),
            _cat("rec_yd", 1, per=10),
            _cat("rec_td", 6),
            _cat("fum", 0),
            _cat("fum_lost", -2),
            _cat("two_pt", 2),
            *(_cat(stat, pts) for stat, pts in _KICKER_POINTS.items()),
            _cat("dst_sack", 3),
            _cat("dst_int", 2),
            _cat("dst_fum_rec", 2),
            _cat("dst_td", 6),
            _cat("dst_safety", 2),
            _cat("dst_blk", 2),
            _cat("dst_return_yd", 1, per=20),
            *_DST_BANDS,
        ],
        fractional=fractional,
    )


def test_qb_worked_example_from_spec() -> None:
    # implementation.md §0.1: 25 cmp, 300 yd, 3 TD → 25 + 20 + 18 = 63.
    assert fantasy_points(
        _league_like(),
        {"pass_cmp": 25, "pass_yd": 300, "pass_td": 3},
    ) == 63


def test_rb_worked_example_from_spec() -> None:
    # implementation.md §0.1: 100 yd, 1 TD, 4 rec → 10 + 6 + 4 = 20.
    assert fantasy_points(
        _league_like(),
        {"rush_yd": 100, "rush_td": 1, "rec": 4},
    ) == 20


def test_wr_and_te_use_reception_and_yardage_slugs() -> None:
    wr = fantasy_points(
        _league_like(),
        {"rec": 8, "rec_yd": 120, "rec_td": 1},
    )
    te = fantasy_points(
        _league_like(),
        {"rec": 5, "rec_yd": 60, "rec_td": 0, "rush_yd": 10},
    )
    assert wr == 8 + 12 + 6
    assert te == 5 + 6 + 1


@pytest.mark.parametrize(
    ("stat", "amount", "expected"),
    [
        ("pass_cmp", 1, 1),
        ("pass_att", 10, 0),
        ("pass_yd", 15, 1),
        ("pass_td", 1, 6),
        ("pass_int", 1, -1),
        ("rush_att", 10, 0),
        ("rush_yd", 10, 1),
        ("rush_td", 1, 6),
        ("rec", 1, 1),
        ("rec_yd", 10, 1),
        ("rec_td", 1, 6),
        ("fum", 1, 0),
        ("fum_lost", 1, -2),
        ("two_pt", 1, 2),
        ("dst_sack", 1, 3),
        ("dst_int", 1, 2),
        ("dst_fum_rec", 1, 2),
        ("dst_td", 1, 6),
        ("dst_safety", 1, 2),
        ("dst_blk", 1, 2),
        ("dst_return_yd", 20, 1),
        *[(stat, 1, pts) for stat, pts in _KICKER_POINTS.items()],
    ],
)
def test_each_counting_and_rate_category(stat: str, amount: int, expected: int) -> None:
    assert fantasy_points(_league_like(), {stat: amount}) == expected


@pytest.mark.parametrize(
    ("pts_allowed", "expected"),
    [
        (0, 10),
        (3, 7),
        (10, 4),
        (17, 1),
        (24, 0),
        (30, -1),
        (40, -4),
        (100, 0),
    ],
)
def test_dst_points_allowed_tiers(pts_allowed: int, expected: int) -> None:
    scoring = _table(_DST_BANDS)
    assert fantasy_points(scoring, {"dst_pts_allowed": pts_allowed}) == expected


@pytest.mark.parametrize(
    ("yds_allowed", "expected"),
    [
        (50, 10),
        (150, 5),
        (250, 0),
        (350, -3),
        (450, -5),
        (1000, 0),
    ],
)
def test_dst_yards_allowed_tiers(yds_allowed: int, expected: int) -> None:
    scoring = _table(_DST_BANDS)
    assert fantasy_points(scoring, {"dst_yds_allowed": yds_allowed}) == expected


def test_dst_combines_sacks_returns_and_tiers() -> None:
    # 2 sacks (6) + 40 return yd (2) + shutout (10) + 80 yd allowed (10) = 28.
    assert fantasy_points(
        _league_like(),
        {
            "dst_sack": 2,
            "dst_return_yd": 40,
            "dst_pts_allowed": 0,
            "dst_yds_allowed": 80,
        },
    ) == 28


def test_leftover_yards_discarded_when_fractional_off() -> None:
    scoring = _table([_cat("pass_yd", 1, per=15)], fractional=False)
    assert fantasy_points(scoring, {"pass_yd": 299}) == 19


def test_leftover_yards_kept_when_fractional_on() -> None:
    scoring = _table([_cat("pass_yd", 1, per=15)], fractional=True)
    result = fantasy_points(scoring, {"pass_yd": 299})
    assert isinstance(result, float)
    assert result == pytest.approx(299 / 15)


def test_integer_rounding_of_projected_counting_stats() -> None:
    scoring = _table([_cat("pass_td", 6)], fractional=False)
    assert fantasy_points(scoring, {"pass_td": 2.4}) == 14
    assert fantasy_points(scoring, {"pass_td": 2.5}) == 15


def test_half_away_from_zero_on_negative_total() -> None:
    scoring = _table([_cat("pass_int", -1)], fractional=False)
    assert fantasy_points(scoring, {"pass_int": 2.5}) == -3


def test_fractional_flag_returns_unrounded_float() -> None:
    scoring = _table([_cat("pass_td", 6)], fractional=True)
    result = fantasy_points(scoring, {"pass_td": 2.4})
    assert result == pytest.approx(14.4)
    assert isinstance(result, float)


def test_missing_slugs_score_zero() -> None:
    assert fantasy_points(_league_like(), {}) == 0


def test_ignores_provider_point_total() -> None:
    scoring = _table([_cat("pass_td", 6)])
    padded = {
        "pass_td": 1,
        "fantasy_points": 99,
        "pts": 99,
        "points": 99,
        "fpts": 99,
    }
    assert fantasy_points(scoring, padded) == 6


def test_negative_category_applies_as_written_a6() -> None:
    # A-6 unresolved: an INT is -1, not stripped and not floored at 0.
    scoring = _table([_cat("pass_int", -1)], fractional=False)
    assert fantasy_points(scoring, {"pass_int": 1}) == -1


def test_overlapping_bands_both_apply() -> None:
    scoring = _table(
        [
            _cat("dst_pts_allowed", 5, bounds=(0, 10)),
            _cat("dst_pts_allowed", 3, bounds=(5, 15)),
        ]
    )
    assert fantasy_points(scoring, {"dst_pts_allowed": 7}) == 8


def test_rejects_non_numeric_stat() -> None:
    scoring = _table([_cat("pass_td", 6)])
    with pytest.raises(DataError, match="pass_td"):
        fantasy_points(scoring, {"pass_td": "3"})


def test_rejects_bool_stat() -> None:
    scoring = _table([_cat("pass_td", 6)])
    with pytest.raises(DataError, match="pass_td"):
        fantasy_points(scoring, {"pass_td": True})


def test_rejects_non_finite_stat() -> None:
    scoring = _table([_cat("pass_td", 6)])
    with pytest.raises(DataError, match="finite"):
        fantasy_points(scoring, {"pass_td": math.inf})


def test_none_stat_is_zero() -> None:
    scoring = _table([_cat("pass_td", 6)])
    assert fantasy_points(scoring, {"pass_td": None}) == 0


def test_missing_band_stat_is_not_a_shutout() -> None:
    # 0 is a real DST shutout; a missing slug is not.
    assert fantasy_points(_league_like(), {"pass_td": 1}) == 6
    assert fantasy_points(_league_like(), {"dst_pts_allowed": 0}) == 10


def test_explicit_zero_matches_zero_band() -> None:
    scoring = _table([_cat("dst_pts_allowed", 10, bounds=(0, 0))])
    assert fantasy_points(scoring, {"dst_pts_allowed": 0}) == 10
    assert fantasy_points(scoring, {}) == 0


def test_points_scale_a_rate_category() -> None:
    scoring = _table([_cat("pass_yd", 2, per=15)], fractional=False)
    assert fantasy_points(scoring, {"pass_yd": 30}) == 4


def test_kicker_line_sums_makes_and_misses() -> None:
    assert fantasy_points(
        _league_like(),
        {
            "fg_30_39": 2,
            "fg_50_59": 1,
            "fg_miss_40_49": 1,
            "pat_made": 3,
            "pat_miss": 1,
        },
    ) == (3 + 3) + 5 + (-2) + 3 + (-1)

from __future__ import annotations

import pytest

from draft.errors import DraftError
from draft.snake import (
    draft_length,
    is_snake_turn,
    next_our_overall,
    next_overall,
    our_overalls,
    overall_pick,
    slot_on_the_clock,
)


@pytest.mark.parametrize(
    ("overall", "team_count", "slot"),
    [
        (1, 8, 1),
        (8, 8, 8),
        (9, 8, 8),
        (10, 8, 7),
        (16, 8, 1),
        (17, 8, 1),
        (1, 12, 1),
        (12, 12, 12),
        (13, 12, 12),
        (24, 12, 1),
        (25, 12, 1),
        (5, 10, 5),
        (11, 10, 10),
        (12, 10, 9),
    ],
)
def test_slot_on_the_clock(overall: int, team_count: int, slot: int) -> None:
    assert slot_on_the_clock(overall, team_count) == slot


@pytest.mark.parametrize(
    ("round_number", "slot", "team_count", "overall"),
    [
        (1, 1, 8, 1),
        (1, 8, 8, 8),
        (2, 8, 8, 9),
        (2, 1, 8, 16),
        (3, 1, 8, 17),
        (1, 1, 12, 1),
        (2, 1, 12, 24),
        (3, 1, 12, 25),
        (2, 12, 12, 13),
    ],
)
def test_overall_pick(
    round_number: int, slot: int, team_count: int, overall: int
) -> None:
    assert overall_pick(round_number, slot, team_count) == overall
    assert slot_on_the_clock(overall, team_count) == slot


def test_our_picks_and_turn_at_slot_8_of_8() -> None:
    assert our_overalls(8, 8, 4) == (8, 9, 24, 25)
    assert next_our_overall(1, 8, 8, 4) == 8
    assert next_our_overall(8, 8, 8, 4) == 8
    assert next_our_overall(9, 8, 8, 4) == 9
    assert next_our_overall(10, 8, 8, 4) == 24
    assert is_snake_turn(8, 8, 8, 4)
    assert is_snake_turn(9, 8, 8, 4) is False
    assert is_snake_turn(1, 8, 8, 4) is False


def test_our_picks_slot_1_of_12() -> None:
    assert our_overalls(1, 12, 3) == (1, 24, 25)
    assert is_snake_turn(24, 1, 12, 3)
    assert is_snake_turn(1, 1, 12, 3) is False


def test_next_overall_and_length() -> None:
    assert next_overall(0) == 1
    assert next_overall(16) == 17
    assert draft_length(10, 15) == 150
    assert next_our_overall(151, 1, 10, 15) is None


def test_rejects_non_positive_inputs() -> None:
    with pytest.raises(DraftError):
        slot_on_the_clock(0, 8)
    with pytest.raises(DraftError):
        overall_pick(1, 9, 8)
    with pytest.raises(DraftError):
        next_overall(-1)

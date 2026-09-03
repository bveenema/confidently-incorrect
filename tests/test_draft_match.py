from __future__ import annotations

from data.pool import PooledPlayer
from draft.match import find_by_key, match_players, player_key


def _p(
    name: str,
    *,
    position: str = "QB",
    team: str = "BUF",
    yahoo_id: str | None = None,
    fpid: int | None = None,
) -> PooledPlayer:
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
        yahoo_id=yahoo_id,
        fpid=fpid,
        tank_id=None,
        fp_points=10,
        tank_points=None,
        source_delta=None,
        value_rank=1,
        pos_rank=1,
        adp=None,
        adp_delta=None,
        tier=1,
        tier_break_after=False,
        scoring_incomplete=False,
        join="yahoo_id",
    )


def test_yahoo_id_and_normalized_name() -> None:
    players = (
        _p("A.J. Brown", position="WR", team="PHI", yahoo_id="99"),
        _p("Josh Allen", yahoo_id="1"),
    )
    assert match_players(players, "99") == (players[0],)
    assert match_players(players, "AJ Brown") == (players[0],)
    assert match_players(players, "a.j. brown") == (players[0],)


def test_unique_last_name_and_ambiguous() -> None:
    players = (
        _p("Josh Allen", team="BUF", yahoo_id="1"),
        _p("Josh Allen", position="WR", team="JAX", yahoo_id="2"),
        _p("Saquon Barkley", position="RB", team="PHI", yahoo_id="3"),
    )
    assert match_players(players, "Barkley") == (players[2],)
    hits = match_players(players, "Allen")
    assert players[0] in hits and players[1] in hits
    assert match_players(players, "Josh Allen") == (players[0], players[1])


def test_dst_by_team_abbrev() -> None:
    players = (_p("Jacksonville", position="DST", team="JAX", yahoo_id="50"),)
    assert match_players(players, "JAC") == players
    assert match_players(players, "jax") == players


def test_player_key_prefers_yahoo_id() -> None:
    player = _p("Jane Doe", yahoo_id="7", fpid=3)
    assert player_key(player) == "yahoo:7"
    assert find_by_key((player,), "yahoo:7") is player
    assert find_by_key((player,), "missing") is None


def test_empty_query() -> None:
    assert match_players((_p("Jane"),), "   ") == ()
    assert match_players((_p("Jane"),), "nobody") == ()

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tests.test_league_settings import TEMPLATE
from tests.test_scoring import _cat, _league_like, _table
from tests.test_tank01 import PLAYERS, PROJ_SEASON

from data import DataAPIError
from data.__main__ import format_player_pool, main
from data.fantasypros import ConsensusRank, FantasyProsClient, PlayerProjection
from data.league_settings import load_league_settings_file
from data.pool import (
    PooledPlayer,
    adp_scoring_type,
    assign_tiers,
    build_player_pool,
    load_player_pool,
    normalize_name,
    normalize_position,
    normalize_team,
    qb_inflation_check,
    scoring_incomplete,
)
from data.tank01 import PlayerIdentity, ProjectionSet, Tank01Client
from data.tank01 import PlayerProjection as TankProj


def _fp(
    fpid: int,
    name: str,
    position: str,
    team: str,
    stats: dict[str, float],
) -> PlayerProjection:
    return PlayerProjection(
        fpid=fpid, name=name, position=position, team=team, stats=stats
    )


def _tank(
    player_id: str,
    name: str,
    position: str,
    team: str,
    stats: dict[str, float],
) -> TankProj:
    return TankProj(
        player_id=player_id, name=name, position=position, team=team, stats=stats
    )


def _adp(
    fpid: int,
    name: str,
    position: str,
    team: str,
    *,
    yahoo_id: str | None = None,
    rank_ecr: int | None = None,
    rank_ave: float | None = None,
) -> ConsensusRank:
    return ConsensusRank(
        fpid=fpid,
        yahoo_id=yahoo_id,
        name=name,
        position=position,
        team=team,
        rank_ecr=rank_ecr,
        rank_ave=rank_ave,
        rank_std=None,
        rank_min=None,
        rank_max=None,
        tier=None,
    )


def _ident(
    player_id: str,
    name: str,
    position: str,
    team: str,
    yahoo_id: str | None,
) -> PlayerIdentity:
    return PlayerIdentity(
        player_id=player_id,
        yahoo_id=yahoo_id,
        name=name,
        position=position,
        team=team,
    )


def _tank_set(
    players: tuple[TankProj, ...] = (),
    defenses: tuple[TankProj, ...] = (),
) -> ProjectionSet:
    return ProjectionSet(season=2026, week="season", players=players, defenses=defenses)


def test_normalize_name_drops_suffix_and_punctuation() -> None:
    assert normalize_name("Patrick Mahomes II") == "patrick mahomes"
    assert normalize_name("A.J. Brown") == normalize_name("AJ Brown")


def test_normalize_position_and_team_aliases() -> None:
    assert normalize_position("DEF") == "DST"
    assert normalize_position("PK") == "K"
    assert normalize_team("JAC") == normalize_team("JAX")
    assert normalize_team("WSH") == normalize_team("WAS")


def test_adp_scoring_type_follows_reception_category() -> None:
    assert adp_scoring_type(_league_like()) == "PPR"
    assert adp_scoring_type(_table([_cat("rec", 0.5), _cat("pass_td", 6)])) == "HALF"
    assert adp_scoring_type(_table([_cat("pass_td", 6)])) == "STD"
    assert adp_scoring_type(_table([_cat("rec", 0), _cat("pass_td", 6)])) == "STD"


def test_k_and_dst_incomplete_when_scored_slugs_missing() -> None:
    scoring = _league_like()
    assert scoring_incomplete("K", {"fg": 30.0, "fga": 35.0, "pat_made": 40.0}, scoring)
    assert scoring_incomplete("DST", {"dst_sack": 40.0, "dst_int": 12.0}, scoring)
    assert not scoring_incomplete(
        "DST", {"dst_sack": 40.0, "dst_return_yd": 800.0}, scoring
    )
    assert not scoring_incomplete("QB", {"pass_yd": 4000.0}, scoring)


def test_tiers_break_on_a_cliff_not_even_spacing() -> None:
    cliffs = assign_tiers([100.0, 99.0, 80.0, 79.0])
    assert [tier for tier, _ in cliffs] == [1, 1, 2, 2]
    assert cliffs[1][1] is True
    even = assign_tiers([100.0, 90.0, 80.0, 70.0])
    assert [tier for tier, _ in even] == [1, 1, 1, 1]
    assert not any(break_after for _, break_after in even)


def test_merge_on_yahoo_id_despite_name_mismatch() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [
            _fp(
                1,
                "Alpha QB",
                "QB",
                "BUF",
                {"pass_cmp": 25, "pass_yd": 300, "pass_td": 3},
            )
        ],
        _tank_set(
            players=(
                _tank(
                    "9",
                    "Totally Different",
                    "QB",
                    "PHI",
                    {"pass_cmp": 20, "pass_yd": 250, "pass_td": 2},
                ),
            )
        ),
        [_adp(1, "Alpha QB", "QB", "BUF", yahoo_id="100", rank_ecr=24, rank_ave=24.6)],
        [_ident("9", "Totally Different", "QB", "PHI", "100")],
        season=2026,
    )
    assert len(pool.players) == 1
    row = pool.players[0]
    assert row.join == "yahoo_id"
    assert row.fp_points == 63
    assert row.tank_points == 48
    assert row.source_delta == 15
    assert row.adp == 24.6
    assert row.value_rank == 1
    assert row.adp_delta == pytest.approx(23.6)


def test_merge_on_name_team_pos_when_yahoo_missing() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [_fp(2, "Jane Doe Jr.", "RB", "KC", {"rush_yd": 100, "rush_td": 1, "rec": 4})],
        _tank_set(
            players=(
                _tank(
                    "8",
                    "Jane Doe",
                    "RB",
                    "KC",
                    {"rush_yd": 90, "rush_td": 1, "rec": 3},
                ),
            )
        ),
        [_adp(2, "Jane Doe", "RB", "KC", rank_ecr=40)],
        [_ident("8", "Jane Doe", "RB", "KC", None)],
        season=2026,
    )
    row = pool.players[0]
    assert row.join == "name_team_pos"
    assert row.fp_points == 20
    assert row.tank_points == 18
    assert row.source_delta == 2
    assert row.adp == 40.0


def test_dst_joins_on_team_alias() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [_fp(3, "Jacksonville", "DST", "JAC", {"dst_sack": 10})],
        _tank_set(
            defenses=(
                _tank("22", "JAX DST", "DST", "JAX", {"dst_sack": 8, "dst_blk": 1}),
            )
        ),
        [_adp(3, "Jacksonville", "DST", "JAC", rank_ecr=120)],
        (),
        season=2026,
    )
    row = pool.players[0]
    assert row.join == "team_dst"
    assert row.scoring_incomplete is True
    assert row.fp_points == 30
    assert row.tank_points == 26


def test_k_incomplete_excluded_from_adp_gap_list() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [
            _fp(
                4,
                "Star QB",
                "QB",
                "BAL",
                {"pass_cmp": 30, "pass_yd": 400, "pass_td": 4},
            ),
            _fp(5, "Boot", "K", "NYJ", {"fg": 30.0, "pat_made": 40.0}),
        ],
        _tank_set(),
        [
            _adp(4, "Star QB", "QB", "BAL", rank_ecr=20),
            _adp(5, "Boot", "K", "NYJ", rank_ecr=150),
        ],
        (),
        season=2026,
    )
    kicker = next(p for p in pool.players if p.position == "K")
    assert kicker.scoring_incomplete is True
    assert kicker.value_rank is None
    assert kicker.adp_delta is None
    assert all(p.position != "K" for p in pool.by_adp_gap())


def test_tank_only_row_has_no_value_rank() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [_fp(6, "Only FP", "WR", "DAL", {"rec": 80, "rec_yd": 1000, "rec_td": 8})],
        _tank_set(
            players=(_tank("77", "Only Tank", "WR", "MIA", {"rec": 70, "rec_yd": 900}),)
        ),
        [_adp(6, "Only FP", "WR", "DAL", rank_ecr=15)],
        [_ident("77", "Only Tank", "WR", "MIA", "999")],
        season=2026,
    )
    by_name = {p.name: p for p in pool.players}
    assert by_name["Only FP"].join == "fp_only"
    assert by_name["Only Tank"].join == "tank_only"
    assert by_name["Only Tank"].value_rank is None
    assert by_name["Only Tank"].fp_points is None


def test_qb_inflation_passes_when_top_qbs_outrank_adp() -> None:
    scoring = _league_like()
    qbs = []
    adp_rows = []
    for index, (fpid, adp) in enumerate(((10, 25.0), (11, 30.0), (12, 28.0)), start=1):
        qbs.append(
            _fp(
                fpid,
                f"QB{index}",
                "QB",
                "BUF",
                {"pass_cmp": 40 - index, "pass_yd": 4500, "pass_td": 40},
            )
        )
        adp_rows.append(
            _adp(fpid, f"QB{index}", "QB", "BUF", rank_ave=adp, rank_ecr=int(adp))
        )
    pool = build_player_pool(scoring, qbs, _tank_set(), adp_rows, (), season=2026)
    assert pool.qb_inflation.ok is True
    assert pool.qb_inflation.median_gap is not None
    assert pool.qb_inflation.median_gap >= 8


def test_qb_inflation_fails_when_ranks_match_adp() -> None:
    rows = [
        PooledPlayer(
            name=f"QB{rank}",
            position="QB",
            team="BUF",
            yahoo_id=None,
            fpid=rank,
            tank_id=None,
            fp_points=400 - rank,
            tank_points=None,
            source_delta=None,
            value_rank=rank,
            pos_rank=rank,
            adp=float(rank),
            adp_delta=0.0,
            tier=1,
            tier_break_after=False,
            scoring_incomplete=False,
            join="fp_only",
        )
        for rank in (1, 2, 3)
    ]
    check = qb_inflation_check(rows)
    assert check.ok is False
    assert check.median_gap == 0.0


def test_load_player_pool_rejects_truncated_fantasypros(tmp_path: Path) -> None:
    settings = load_league_settings_file(TEMPLATE)  # fake values; scoring shape only

    class _FP:
        def projections(self, season: int, *, week: int) -> object:
            return type(
                "P",
                (),
                {"truncated": True, "players": (1,), "advertised_count": 50},
            )()

        def consensus_rankings(self, *args: object, **kwargs: object) -> tuple:
            return ()

    class _Tank:
        def projections(self, *, week: str) -> object:
            return _tank_set(players=(_tank("1", "X", "QB", "BUF", {}),))

        def player_list(self) -> tuple:
            return ()

    with pytest.raises(DataAPIError, match="truncated"):
        load_player_pool(settings, _FP(), _Tank(), season=2026)


def test_load_player_pool_rejects_empty_player_list() -> None:
    settings = load_league_settings_file(TEMPLATE)

    class _FP:
        def projections(self, season: int, *, week: int) -> object:
            return type(
                "P",
                (),
                {
                    "truncated": False,
                    "players": (_fp(1, "A", "QB", "BUF", {"pass_cmp": 1}),),
                    "advertised_count": 1,
                },
            )()

        def consensus_rankings(self, *args: object, **kwargs: object) -> tuple:
            return (_adp(1, "A", "QB", "BUF", rank_ecr=1),)

    class _Tank:
        def projections(self, *, week: str) -> object:
            return _tank_set(players=(_tank("1", "X", "QB", "BUF", {}),))

        def player_list(self) -> tuple:
            return ()

    with pytest.raises(DataAPIError, match="player_list"):
        load_player_pool(settings, _FP(), _Tank(), season=2026)


def test_cli_player_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload["team_count"] = 8
    payload["scoring"]["fractional_points"] = False
    payload["scoring"]["categories"] = [
        {"stat": "pass_cmp", "points": 1},
        {"stat": "pass_yd", "points": 1, "per": 15},
        {"stat": "pass_td", "points": 6},
        {"stat": "rec", "points": 1},
        {"stat": "fg_0_19", "points": 3},
        {"stat": "dst_return_yd", "points": 1, "per": 20},
        {"stat": "dst_sack", "points": 3},
    ]
    (tmp_path / "league-settings.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    (tmp_path / "tokens").mkdir()
    (tmp_path / "tokens" / "fantasypros.json").write_text(
        json.dumps({"api_key": "fp-key"}), encoding="utf-8"
    )
    (tmp_path / "tokens" / "tank01.json").write_text(
        json.dumps({"api_key": "tank-key"}), encoding="utf-8"
    )

    def fp_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/projections"):
            return httpx.Response(
                200,
                json={
                    "season": "2026",
                    "week": "0",
                    "count": "1",
                    "players": [
                        {
                            "fpid": 111,
                            "name": "Example QB",
                            "position_id": "QB",
                            "team_id": "BUF",
                            "stats": {
                                "pass_cmp": 333.0,
                                "pass_yds": 3813.0,
                                "pass_tds": 27.0,
                            },
                        }
                    ],
                },
            )
        assert request.url.params.get("type") == "ADP"
        assert request.url.params.get("position") == "ALL"
        return httpx.Response(
            200,
            json={
                "players": [
                    {
                        "player_id": 111,
                        "player_name": "Example QB",
                        "player_position_id": "QB",
                        "player_team_id": "BUF",
                        "player_yahoo_id": "1",
                        "rank_ecr": 24,
                        "rank_ave": "24.6",
                    }
                ]
            },
        )

    def tank_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getNFLPlayerList"):
            return httpx.Response(200, json=PLAYERS)
        return httpx.Response(200, json=PROJ_SEASON)

    fp_http = httpx.Client(transport=httpx.MockTransport(fp_handler))
    tank_http = httpx.Client(transport=httpx.MockTransport(tank_handler))
    monkeypatch.setattr(
        "data.__main__.FantasyProsClient",
        lambda root: FantasyProsClient(root, http=fp_http),
    )
    monkeypatch.setattr(
        "data.__main__.Tank01Client",
        lambda root: Tank01Client(root, http=tank_http),
    )
    assert main(["player-pool", "--season", "2026"]) == 0
    out = capsys.readouterr().out
    assert "ok:" in out
    assert "ADP gaps" in out
    assert "QB inflation" in out
    assert "FantasyPros" in out
    assert "Tank01" in out


def test_format_includes_both_source_values() -> None:
    scoring = _league_like()
    pool = build_player_pool(
        scoring,
        [
            _fp(
                1,
                "Alpha QB",
                "QB",
                "BUF",
                {"pass_cmp": 25, "pass_yd": 300, "pass_td": 3},
            )
        ],
        _tank_set(
            players=(
                _tank(
                    "9",
                    "Alpha QB",
                    "QB",
                    "BUF",
                    {"pass_cmp": 20, "pass_yd": 250, "pass_td": 2},
                ),
            )
        ),
        [_adp(1, "Alpha QB", "QB", "BUF", rank_ecr=24)],
        (),
        season=2026,
    )
    text = format_player_pool(pool)
    assert "63" in text
    assert "48" in text
    assert "15" in text

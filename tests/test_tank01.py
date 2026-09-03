from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tests.test_scoring import _league_like

from data import DataAPIError, DataConfigError, Tank01Client
from data.__main__ import main
from data.scoring import fantasy_points
from data.tank01 import (
    ATTRIBUTION,
    credentials_path,
    implied_totals_from_game,
    load_credentials,
    map_defense_stats,
    map_player_stats,
)


def _write_key(root: Path, key: str = "test-key") -> None:
    path = credentials_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_key": key}), encoding="utf-8")


def _client(root: Path, handler) -> Tank01Client:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return Tank01Client(root, http=http)


PROJ_SEASON = {
    "statusCode": 200,
    "body": {
        "season": "2026",
        "week": "season",
        "playerProjections": {
            "4040715": {
                "playerID": "4040715",
                "longName": "Jalen Hurts",
                "pos": "QB",
                "team": "PHI",
                "teamID": "27",
                "fumblesLost": "3.1",
                "twoPointConversion": "0.5",
                "Passing": {
                    "passAttempts": "480",
                    "passCompletions": "320",
                    "passYds": "3800",
                    "passTD": "26",
                    "int": "9",
                },
                "Rushing": {"carries": "140", "rushYds": "600", "rushTD": "10"},
                "Receiving": {
                    "receptions": "0",
                    "targets": "0",
                    "recYds": "0",
                    "recTD": "0",
                },
                "fantasyPointsDefault": {
                    "standard": "300",
                    "PPR": "300",
                    "halfPPR": "300",
                },
            },
            "3124679": {
                "playerID": "3124679",
                "longName": "Example Kicker",
                "pos": "PK",
                "team": "NYJ",
                "teamID": "25",
                "Kicking": {
                    "fgMade": "24.3",
                    "fgMissed": "3.3",
                    "xpMade": "32.7",
                    "xpMissed": "1.9",
                },
                "fantasyPointsDefault": {
                    "standard": "100.4",
                    "PPR": "100.4",
                    "halfPPR": "100.4",
                },
            },
        },
        "teamDefenseProjections": {
            "22": {
                "teamID": "22",
                "teamAbv": "PHI",
                "sacks": "42",
                "interceptions": "14",
                "fumbleRecoveries": "9",
                "defTD": "2",
                "safeties": "1",
                "blockKick": "1",
                "ptsAgainst": "20.5",
                "returnTD": "1",
                "fantasyPointsDefault": "110",
            }
        },
    },
}

PROJ_WEEK1 = {
    "statusCode": 200,
    "body": {
        "season": "2026",
        "week": "1",
        "playerProjections": {
            "4040715": {
                "playerID": "4040715",
                "longName": "Jalen Hurts",
                "pos": "QB",
                "team": "PHI",
                "teamID": "27",
                "fumblesLost": "0.2",
                "twoPointConversion": "0",
                "Passing": {
                    "passAttempts": "28.2",
                    "passCompletions": "18.1",
                    "passYds": "221",
                    "passTD": "1.5",
                    "int": "0.5",
                },
                "Rushing": {"carries": "6.5", "rushYds": "27.3", "rushTD": "0.5"},
                "Receiving": {
                    "receptions": "0",
                    "targets": "0",
                    "recYds": "0",
                    "recTD": "0",
                },
                "fantasyPointsDefault": {
                    "standard": "20.07",
                    "PPR": "20.07",
                    "halfPPR": "20.07",
                },
            }
        },
        "teamDefenseProjections": {
            "22": {
                "teamID": "22",
                "teamAbv": "PHI",
                "sacks": "2.5",
                "interceptions": "0.9",
                "fumbleRecoveries": "0.4",
                "defTD": "0.1",
                "safeties": "0",
                "blockKick": "0",
                "ptsAgainst": "17.2",
                "returnTD": "0",
                "fantasyPointsDefault": "8",
            }
        },
    },
}

PLAYERS = {
    "statusCode": 200,
    "body": [
        {
            "playerID": "1",
            "longName": "Healthy Player",
            "pos": "WR",
            "team": "DAL",
            "yahooPlayerID": "100",
            "injury": {
                "designation": "",
                "description": "",
                "injDate": "",
                "injReturnDate": "",
            },
        },
        {
            "playerID": "2",
            "longName": "Hurt Player",
            "pos": "RB",
            "team": "KC",
            "yahooPlayerID": "200",
            "injury": {
                "designation": "Questionable",
                "description": "ankle",
                "injDate": "20240501",
                "injReturnDate": "20260914",
            },
        },
    ],
}

NEWS = {
    "statusCode": 200,
    "body": [
        {
            "title": "Example depth chart note",
            "link": "https://example.com/news",
            "image": "https://example.com/img.png",
            "playerIDs": ["5083754"],
        }
    ],
}

ODDS = {
    "statusCode": 200,
    "body": {
        "20260828_ARI@GB": {
            "gameID": "20260828_ARI@GB",
            "gameDate": "20260828",
            "homeTeam": "GB",
            "awayTeam": "ARI",
            "teamIDHome": "12",
            "teamIDAway": "1",
            "draftkings": {
                "totalOver": "36.5",
                "totalUnder": "36.5",
                "homeTeamSpread": "-1.5",
                "awayTeamSpread": "1.5",
                "homeTeamML": "-121",
                "awayTeamML": "+101",
            },
        }
    },
}


def test_missing_credentials(tmp_path: Path) -> None:
    with pytest.raises(DataConfigError, match="tank01"):
        load_credentials(tmp_path)


def test_placeholder_key_rejected(tmp_path: Path) -> None:
    _write_key(tmp_path, "REPLACE_ME")
    with pytest.raises(DataConfigError, match="api_key"):
        load_credentials(tmp_path)


def test_map_player_stats_drops_points_and_renames() -> None:
    mapped = map_player_stats(
        PROJ_SEASON["body"]["playerProjections"]["4040715"]  # type: ignore[index]
    )
    assert "fantasyPointsDefault" not in mapped
    assert mapped["pass_cmp"] == 320
    assert mapped["pass_yd"] == 3800
    assert mapped["pass_td"] == 26
    assert mapped["pass_int"] == 9
    assert mapped["rush_att"] == 140
    assert mapped["fum_lost"] == 3.1
    assert mapped["two_pt"] == 0.5
    kicker = map_player_stats(
        PROJ_SEASON["body"]["playerProjections"]["3124679"]  # type: ignore[index]
    )
    assert kicker["fg"] == 24.3
    assert kicker["fga"] == 27.6
    assert kicker["pat_made"] == 32.7
    assert kicker["pat_miss"] == 1.9


def test_map_defense_stats() -> None:
    mapped = map_defense_stats(
        PROJ_SEASON["body"]["teamDefenseProjections"]["22"]  # type: ignore[index]
    )
    assert mapped["dst_sack"] == 42
    assert mapped["dst_int"] == 14
    assert mapped["dst_pts_allowed"] == 20.5
    assert mapped["dst_blk"] == 1
    assert "dst_return_yd" not in mapped
    assert "returnTD" not in mapped


def test_mapped_line_scores_with_league_table() -> None:
    mapped = map_player_stats(
        PROJ_SEASON["body"]["playerProjections"]["4040715"]  # type: ignore[index]
    )
    total = fantasy_points(_league_like(), mapped)
    assert total != 300
    assert total > 0


def test_implied_totals_from_spread_and_total() -> None:
    derived = implied_totals_from_game(ODDS["body"]["20260828_ARI@GB"])  # type: ignore[index]
    assert derived is not None
    assert derived.book == "draftkings"
    assert derived.total == 36.5
    assert derived.home_spread == -1.5
    assert derived.home_implied == 19.0
    assert derived.away_implied == 17.5


def test_projections_season_and_week(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-rapidapi-key"] == "test-key"
        assert request.headers["x-rapidapi-host"]
        week = request.url.params.get("week")
        body = PROJ_WEEK1 if week == "1" else PROJ_SEASON
        return httpx.Response(200, json=body)

    with _client(tmp_path, handler) as client:
        season = client.projections(week="season")
        weekly = client.projections(week=1)
    assert season.week == "season"
    assert weekly.week == "1"
    assert season.players[0].stats["pass_yd"] == 3800
    assert "fantasyPointsDefault" not in season.players[0].stats
    qb = next(p for p in weekly.players if p.position == "QB")
    assert qb.stats["pass_cmp"] == 18.1
    kicker = next(p for p in season.players if p.position == "K")
    assert kicker.position == "K"
    assert season.defenses[0].position == "DST"
    assert season.defenses[0].stats["dst_sack"] == 42


def test_injuries_and_news(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getNFLPlayerList"):
            return httpx.Response(200, json=PLAYERS)
        assert "recentNews" in str(request.url)
        return httpx.Response(200, json=NEWS)

    with _client(tmp_path, handler) as client:
        injuries = client.injuries()
        news = client.news(recent=True)
    assert len(injuries) == 1
    assert injuries[0].designation == "Questionable"
    assert injuries[0].yahoo_id == "200"
    assert news[0].title.startswith("Example")
    assert news[0].player_ids == ("5083754",)


def test_player_list_includes_healthy(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getNFLPlayerList")
        return httpx.Response(200, json=PLAYERS)

    with _client(tmp_path, handler) as client:
        rows = client.player_list()
    assert {row.player_id for row in rows} == {"1", "2"}
    healthy = next(row for row in rows if row.player_id == "1")
    assert healthy.yahoo_id == "100"
    assert healthy.position == "WR"


def test_implied_team_totals(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("gameDate") == "20260828"
        return httpx.Response(200, json=ODDS)

    with _client(tmp_path, handler) as client:
        totals = client.implied_team_totals("20260828")
    assert len(totals) == 1
    assert totals[0].home_team == "GB"
    assert totals[0].home_implied == 19.0


def test_attribution_string() -> None:
    assert "Tank01" in ATTRIBUTION
    assert "tank01.com" in ATTRIBUTION


def test_http_error_does_not_leak_key(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden api_key=test-key")

    with _client(tmp_path, handler) as client:
        with pytest.raises(DataAPIError, match="403") as exc:
            client.projections(week=1)
    assert "test-key" not in str(exc.value)


def test_smoke_fails_when_empty(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getNFLProjections"):
            return httpx.Response(
                200,
                json={
                    "statusCode": 200,
                    "body": {
                        "season": "2026",
                        "week": "season",
                        "playerProjections": {},
                        "teamDefenseProjections": {},
                    },
                },
            )
        if path.endswith("/getNFLPlayerList"):
            return httpx.Response(200, json=PLAYERS)
        if path.endswith("/getNFLNews"):
            return httpx.Response(200, json=NEWS)
        return httpx.Response(200, json=ODDS)

    with _client(tmp_path, handler) as client:
        with pytest.raises(DataAPIError, match="empty"):
            client.smoke(odds_date="20260828")


def test_cli_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_key(tmp_path)
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getNFLProjections"):
            week = request.url.params.get("week")
            return httpx.Response(200, json=PROJ_WEEK1 if week == "1" else PROJ_SEASON)
        if path.endswith("/getNFLPlayerList"):
            return httpx.Response(200, json=PLAYERS)
        if path.endswith("/getNFLNews"):
            return httpx.Response(200, json=NEWS)
        return httpx.Response(200, json=ODDS)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    monkeypatch.setattr(
        "data.__main__.Tank01Client",
        lambda root: Tank01Client(root, http=http),
    )
    assert main(["tank01-smoke", "--odds-date", "20260828"]) == 0
    out = capsys.readouterr().out
    assert "ok:" in out
    assert "Tank01" in out


def test_cli_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["tank01-smoke", "--odds-date", "20260828"]) == 1
    assert "error:" in capsys.readouterr().err

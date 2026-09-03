from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from tests.test_scoring import _league_like

from data import ATTRIBUTION, DataAPIError, DataConfigError, FantasyProsClient
from data.__main__ import main
from data.fantasypros import credentials_path, load_credentials, map_stat_line
from data.scoring import fantasy_points


def _write_key(root: Path, key: str = "test-key") -> None:
    path = credentials_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_key": key}), encoding="utf-8")


def _client(root: Path, handler) -> FantasyProsClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return FantasyProsClient(root, http=http)


PROJ_QB = {
    "season": "2026",
    "week": "0",
    "count": "1",
    "public_api_limited": False,
    "players": [
        {
            "fpid": 111,
            "name": "Example QB",
            "position_id": "QB",
            "team_id": "BUF",
            "stats": {
                "points": 370.54,
                "points_ppr": 370.54,
                "pass_att": 492.06,
                "pass_cmp": 333.36,
                "pass_yds": 3813.37,
                "pass_tds": 27.46,
                "pass_ints": 11.19,
                "rush_att": 118.15,
                "rush_yds": 585.95,
                "rush_tds": 11.5,
                "fumbles": 4.1,
                "2pt_tds": 0.4,
                "pass_yds_300": 0,
            },
        }
    ],
}

PROJ_WEEK1 = {
    "season": "2026",
    "week": "1",
    "count": "1",
    "players": [
        {
            "fpid": 222,
            "name": "Example Week QB",
            "position_id": "QB",
            "team_id": "PHI",
            "stats": {
                "points": 20.62,
                "pass_cmp": 19.08,
                "pass_yds": 227.91,
                "pass_tds": 1.58,
            },
        }
    ],
}

RANKS = {
    "count": 1,
    "players": [
        {
            "player_id": 22968,
            "player_name": "Example RB",
            "player_position_id": "RB",
            "player_team_id": "DET",
            "player_yahoo_id": "42630",
            "rank_ecr": 1,
            "rank_min": "1",
            "rank_max": "2",
            "rank_std": "0.40",
            "tier": 1,
        }
    ],
}

INJURIES = {
    "count": 1,
    "injuries": [
        {
            "player_id": 26035,
            "yahoo_id": "42630",
            "name": "Example WR",
            "status": "OUT",
            "injury_type": "Hamstring",
            "comment": "injured",
            "probability_of_playing": None,
        }
    ],
}

NEWS = {
    "count": 1,
    "items": [
        {
            "id": 605658,
            "player_id": 18598,
            "title": "Example (hand) limited practice",
            "desc": "Limited Wednesday.",
            "impact": "Not a Week 1 concern.",
            "categories": ["News", "Injury"],
            "created": "2026-09-02 21:00:26",
        }
    ],
}


def test_missing_credentials(tmp_path: Path) -> None:
    with pytest.raises(DataConfigError, match="fantasypros"):
        load_credentials(tmp_path)


def test_placeholder_key_rejected(tmp_path: Path) -> None:
    _write_key(tmp_path, "REPLACE_ME")
    with pytest.raises(DataConfigError, match="api_key"):
        load_credentials(tmp_path)


def test_map_stat_line_drops_points_and_renames() -> None:
    mapped = map_stat_line(PROJ_QB["players"][0]["stats"])
    assert "points" not in mapped
    assert "points_ppr" not in mapped
    assert "pass_yds_300" not in mapped
    assert mapped["pass_yd"] == 3813.37
    assert mapped["pass_td"] == 27.46
    assert mapped["pass_int"] == 11.19
    assert mapped["fum_lost"] == 4.1
    assert mapped["two_pt"] == 0.4
    rb = map_stat_line(
        {
            "points": 99,
            "rec_rec": 71.3,
            "rec_yds": 581.13,
            "rec_tds": 4.13,
            "rush_yds": 1383.71,
        }
    )
    assert rb["rec"] == 71.3
    assert rb["rec_yd"] == 581.13
    assert rb["rec_td"] == 4.13
    kicker = map_stat_line({"points": 151.44, "fg": 34.83, "fga": 39.55, "xpt": 46.96})
    assert kicker["pat_made"] == 46.96
    assert kicker["fg"] == 34.83
    assert kicker["fga"] == 39.55
    dst = map_stat_line(
        {
            "points": 7.91,
            "def_sack": 2.93,
            "def_int": 0.9,
            "def_fr": 0.53,
            "def_td": 0.19,
            "def_safety": 0,
            "def_pa": 16.87,
            "def_tyda": 307.9,
        }
    )
    assert dst["dst_sack"] == 2.93
    assert dst["dst_int"] == 0.9
    assert dst["dst_fum_rec"] == 0.53
    assert dst["dst_td"] == 0.19
    assert dst["dst_pts_allowed"] == 16.87
    assert dst["dst_yds_allowed"] == 307.9


def test_mapped_line_scores_with_league_table() -> None:
    mapped = map_stat_line(PROJ_QB["players"][0]["stats"])
    total = fantasy_points(_league_like(), mapped)
    assert total != 370
    assert total > 0


def test_projections_weekly_and_season(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-key"
        week = request.url.params.get("week")
        body = PROJ_WEEK1 if week == "1" else PROJ_QB
        return httpx.Response(200, json=body)

    with _client(tmp_path, handler) as client:
        season = client.projections(2026, week=0)
        weekly = client.projections(2026, week=1, positions=("QB",))
    assert season.week == 0
    assert weekly.week == 1
    assert season.players[0].stats["pass_yd"] == 3813.37
    assert "points" not in season.players[0].stats
    assert weekly.players[0].stats["pass_yd"] == 227.91
    assert not season.truncated


def test_truncated_flag(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "season": "2026",
                "week": "0",
                "count": "119",
                "public_api_limited": True,
                "players": PROJ_QB["players"],
            },
        )

    with _client(tmp_path, handler) as client:
        result = client.projections(2026, week=0)
    assert result.truncated
    assert result.advertised_count == 119


def test_rankings_capture_std(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert "consensus-rankings" in str(request.url)
        return httpx.Response(200, json=RANKS)

    with _client(tmp_path, handler) as client:
        ranks = client.consensus_rankings(2026, position="RB", scoring="PPR")
    assert ranks[0].rank_std == 0.4
    assert ranks[0].yahoo_id == "42630"
    assert ranks[0].tier == 1


def test_injuries_and_news(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/injuries"):
            return httpx.Response(200, json=INJURIES)
        return httpx.Response(200, json=NEWS)

    with _client(tmp_path, handler) as client:
        injuries = client.injuries()
        news = client.news(category="injury", limit=3)
    assert injuries[0].status == "OUT"
    assert injuries[0].injury_type == "Hamstring"
    assert injuries[0].yahoo_id == "42630"
    assert news[0].impact
    assert "Injury" in news[0].categories


def test_attribution_string() -> None:
    assert "FantasyPros" in ATTRIBUTION
    assert "https://www.fantasypros.com" in ATTRIBUTION


def test_http_error(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden api_key=test-key")

    with _client(tmp_path, handler) as client:
        with pytest.raises(DataAPIError, match="403") as exc:
            client.projections(2026, week=0)
    assert "test-key" not in str(exc.value)


def test_smoke_fails_when_empty(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"season": "2026", "week": "0", "players": []})

    with _client(tmp_path, handler) as client:
        with pytest.raises(DataAPIError, match="empty"):
            client.smoke(2026)


def test_smoke_fails_when_truncated(tmp_path: Path) -> None:
    _write_key(tmp_path)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "season": "2026",
                "week": "0",
                "count": "50",
                "public_api_limited": True,
                "players": PROJ_QB["players"],
            },
        )

    with _client(tmp_path, handler) as client:
        with pytest.raises(DataAPIError, match="truncated"):
            client.smoke(2026)


def test_cli_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_key(tmp_path)
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/projections"):
            week = request.url.params.get("week")
            return httpx.Response(200, json=PROJ_WEEK1 if week == "1" else PROJ_QB)
        if path.endswith("/consensus-rankings"):
            return httpx.Response(200, json=RANKS)
        if path.endswith("/injuries"):
            return httpx.Response(200, json=INJURIES)
        return httpx.Response(200, json=NEWS)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    monkeypatch.setattr(
        "data.__main__.FantasyProsClient",
        lambda root: FantasyProsClient(root, http=http),
    )
    assert main(["fantasypros-smoke", "--season", "2026"]) == 0
    out = capsys.readouterr().out
    assert "ok:" in out
    assert "FantasyPros" in out


def test_cli_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["fantasypros-smoke", "--season", "2026"]) == 1
    assert "error:" in capsys.readouterr().err

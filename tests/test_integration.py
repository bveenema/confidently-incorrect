import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from data.fantasypros import ATTRIBUTION, FantasyProsClient
from data.fantasypros import credentials_exist as fantasypros_credentials_exist
from data.tank01 import ATTRIBUTION as TANK01_ATTRIBUTION
from data.tank01 import Tank01Client
from data.tank01 import credentials_exist as tank01_credentials_exist
from yahoo import YahooClient
from yahoo.tokens import tokens_exist

pytestmark = pytest.mark.integration


def test_live_smoke_own_team_settings_roster() -> None:
    raw = os.environ.get("CI_STATE_DIR")
    if not raw:
        pytest.skip("CI_STATE_DIR is unset")
    root = Path(raw)
    if not tokens_exist(root):
        pytest.skip("Yahoo app credentials or token file missing")
    with YahooClient(root) as client:
        result = client.smoke()
    assert result["team_key"]
    assert result["league_key"]
    assert result["roster_count"] is not None
    assert ".t." in result["team_key"]


def test_live_fantasypros_smoke() -> None:
    raw = os.environ.get("CI_STATE_DIR")
    if not raw:
        pytest.skip("CI_STATE_DIR is unset")
    root = Path(raw)
    if not fantasypros_credentials_exist(root):
        pytest.skip("FantasyPros api_key file missing")
    with FantasyProsClient(root) as client:
        week0 = client.projections(2026, week=0)
        if week0.truncated:
            pytest.skip(
                "FantasyPros key is still free-tier "
                f"({len(week0.players)}/{week0.advertised_count})"
            )
        result = client.smoke(2026)
    assert result["week0_count"] > 10
    assert result["week1_qb_count"] > 10
    assert result["rankings_count"] > 10
    assert result["rank_std_sample"] is not None
    assert result["injuries_count"] >= 1
    assert result["attribution"] == ATTRIBUTION


def test_live_tank01_smoke() -> None:
    raw = os.environ.get("CI_STATE_DIR")
    if not raw:
        pytest.skip("CI_STATE_DIR is unset")
    root = Path(raw)
    if not tank01_credentials_exist(root):
        pytest.skip("Tank01 api_key file missing")
    # Prefer a known preseason slate; fall back to today for odds only.
    odds_date = "20260828"
    with Tank01Client(root) as client:
        result = client.smoke(odds_date=odds_date)
        if result["implied_totals_count"] == 0:
            today = datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
            totals = client.implied_team_totals(today)
            result = {**result, "implied_totals_count": len(totals), "odds_date": today}
    assert result["season_count"] > 100
    assert result["week1_count"] > 100
    assert result["week1_dst_count"] >= 30
    assert result["sample_qb_pass_yd"] is not None
    assert result["sample_qb_pass_yd"] > 0
    assert result["injuries_count"] >= 1
    assert result["news_count"] >= 1
    if result["implied_totals_count"] < 1:
        pytest.skip(f"no betting odds for {result['odds_date']}")
    assert result["attribution"] == TANK01_ATTRIBUTION

import os
from pathlib import Path

import pytest

from data.fantasypros import ATTRIBUTION, FantasyProsClient, credentials_exist
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
    if not credentials_exist(root):
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

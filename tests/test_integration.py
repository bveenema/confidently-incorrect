import os
from pathlib import Path

import pytest

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

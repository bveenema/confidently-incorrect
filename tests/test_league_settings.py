from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from data import LeagueSettingsError, load_league_settings
from data.__main__ import main
from data.league_settings import load_league_settings_file, settings_path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "templates" / "league-settings.json"


def _minimal(team_count: int = 8) -> dict:
    return {
        "schema_version": 1,
        "team_count": team_count,
        "roster_slots": [{"position": "QB", "count": 1}],
        "scoring": {
            "fractional_points": True,
            "negative_points": "example-unresolved",
            "categories": [{"stat": "pass_td", "points": 99}],
        },
        "trade_deadline": "2099-06-01",
        "waiver": {"type": "example-waiver", "days": 7, "process": "example"},
        "playoff": {"teams": 3, "weeks": [1, 2]},
        "draft": {"rounds": 3, "type": "example-draft"},
    }


def _write(path: Path, payload: dict) -> Path:
    target = path / "league-settings.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_template_validates() -> None:
    settings = load_league_settings_file(TEMPLATE)
    assert settings.team_count == 99
    assert settings.schema_version == 1
    assert settings.scoring.categories
    assert any(cat.per == 99 for cat in settings.scoring.categories)
    assert any(cat.bounds == (0, 0) for cat in settings.scoring.categories)
    assert settings.scoring.fractional_points is True
    assert settings.draft_pick_trades is True
    assert settings.ir_adds_from_waivers is True
    assert settings.max_acquisitions == 99


def test_loads_team_count_from_file_not_a_constant(tmp_path: Path) -> None:
    eight = load_league_settings_file(_write(tmp_path, _minimal(8)))
    twelve_dir = tmp_path / "twelve"
    twelve_dir.mkdir()
    twelve = load_league_settings_file(_write(twelve_dir, _minimal(12)))
    assert eight.team_count == 8
    assert twelve.team_count == 12
    assert eight.trade_deadline == date(2099, 6, 1)
    assert eight.roster_slots[0].position == "QB"


def test_load_from_ci_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, _minimal(10))
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    settings = load_league_settings()
    assert settings.team_count == 10
    assert settings.source_path == settings_path(tmp_path)


def test_missing_file_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(LeagueSettingsError, match="missing file") as exc:
        load_league_settings(tmp_path)
    assert "templates/league-settings.json" in str(exc.value)


def test_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "league-settings.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(LeagueSettingsError, match="invalid JSON"):
        load_league_settings(tmp_path)


def test_missing_required_key(tmp_path: Path) -> None:
    payload = _minimal()
    del payload["team_count"]
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="team_count"):
        load_league_settings(tmp_path)


def test_empty_scoring_categories(tmp_path: Path) -> None:
    payload = _minimal()
    payload["scoring"]["categories"] = []
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="scoring.categories"):
        load_league_settings(tmp_path)


def test_team_count_zero(tmp_path: Path) -> None:
    _write(tmp_path, _minimal(0))
    with pytest.raises(LeagueSettingsError, match="team_count"):
        load_league_settings(tmp_path)


def test_team_count_string_is_rejected(tmp_path: Path) -> None:
    payload = _minimal()
    payload["team_count"] = "8"
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="team_count"):
        load_league_settings(tmp_path)


def test_unsupported_schema_version(tmp_path: Path) -> None:
    payload = _minimal()
    payload["schema_version"] = 2
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="schema_version"):
        load_league_settings(tmp_path)


def test_bad_deadline(tmp_path: Path) -> None:
    payload = _minimal()
    payload["trade_deadline"] = "11/28/2026"
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="trade_deadline"):
        load_league_settings(tmp_path)


def test_bad_range(tmp_path: Path) -> None:
    payload = _minimal()
    payload["scoring"]["categories"] = [
        {"stat": "dst_pts_allowed", "points": 10, "range": [6, 1]}
    ]
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="range"):
        load_league_settings(tmp_path)


def test_duplicate_roster_position(tmp_path: Path) -> None:
    payload = _minimal()
    payload["roster_slots"] = [
        {"position": "WR", "count": 1},
        {"position": "WR", "count": 1},
    ]
    _write(tmp_path, payload)
    with pytest.raises(LeagueSettingsError, match="duplicated"):
        load_league_settings(tmp_path)


def test_unset_ci_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI_STATE_DIR", raising=False)
    monkeypatch.setattr(
        "data.league_settings._LINUX_DEFAULT", Path("/nonexistent-ci-state")
    )
    with pytest.raises(LeagueSettingsError, match="CI_STATE_DIR"):
        load_league_settings()


def test_cli_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, _minimal(11))
    assert main(["validate-league-settings", "--path", str(path)]) == 0
    out = capsys.readouterr().out
    assert "ok:" in out
    assert "11 teams" in out
    assert "fractional_points=true" in out


def test_cli_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["validate-league-settings"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "missing file" in err

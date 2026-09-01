from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from yahoo import YahooAPIError, YahooAuthError, YahooClient, YahooConfigError
from yahoo.__main__ import main
from yahoo.oauth import AUTH_URL, TOKEN_URL, authorize_url, needs_refresh
from yahoo.parse import league_key_from_team_key, parse_own_team
from yahoo.paths import app_credentials_path, token_path
from yahoo.tokens import TokenSet, load_app_credentials, load_tokens, save_tokens

OWN_TEAM = {
    "fantasy_content": {
        "users": {
            "0": {
                "user": [
                    {
                        "games": {
                            "0": {
                                "game": [
                                    {"game_key": "461", "code": "nfl"},
                                    {
                                        "teams": {
                                            "0": {
                                                "team": [
                                                    [
                                                        {"team_key": "461.l.99999.t.1"},
                                                        {"team_id": "1"},
                                                        {"name": "Example Side"},
                                                    ]
                                                ]
                                            }
                                        }
                                    },
                                ]
                            }
                        }
                    }
                ]
            }
        }
    }
}

SETTINGS = {
    "fantasy_content": {
        "league": [
            {"league_key": "461.l.99999", "num_teams": 10},
            {
                "settings": [
                    {
                        "roster_positions": [
                            {"roster_position": {"position": "QB", "count": 1}},
                            {"roster_position": {"position": "BN", "count": 6}},
                        ],
                        "stat_categories": {
                            "stats": [
                                {"stat": {"stat_id": "4", "display_name": "Pass Yds"}},
                                {"stat": {"stat_id": "13", "display_name": "Rush Yds"}},
                            ]
                        },
                    }
                ]
            },
        ]
    }
}

ROSTER = {
    "fantasy_content": {
        "team": [
            [{"team_key": "461.l.99999.t.1"}],
            {
                "roster": {
                    "0": {
                        "players": {
                            "0": {
                                "player": [
                                    [{"player_key": "461.p.111"}],
                                    {"selected_position": [{"position": "QB"}]},
                                ]
                            },
                            "1": {
                                "player": [
                                    [{"player_key": "461.p.222"}],
                                    {"selected_position": [{"position": "BN"}]},
                                ]
                            },
                            "count": 2,
                        }
                    }
                }
            },
        ]
    }
}


def _write_app(root: Path) -> None:
    path = app_credentials_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"client_id": "cid", "client_secret": "csecret"}),
        encoding="utf-8",
    )


def _write_token(root: Path, expires_at: float = 9_999_999_999) -> None:
    save_tokens(
        TokenSet(
            access_token="access-old",
            refresh_token="refresh-old",
            expires_at=expires_at,
        ),
        root,
    )


def _client(
    root: Path,
    handler,
    clock=lambda: 1_000.0,
) -> YahooClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return YahooClient(root, http=http, clock=clock)


def test_authorize_url_is_oob() -> None:
    url = authorize_url("cid")
    assert url.startswith(AUTH_URL)
    assert "redirect_uri=oob" in url
    assert "response_type=code" in url
    assert "scope=fspt-w" in url


def test_token_survives_reload(tmp_path: Path) -> None:
    _write_token(tmp_path)
    loaded = load_tokens(tmp_path)
    assert loaded.access_token == "access-old"
    assert loaded.refresh_token == "refresh-old"
    assert token_path(tmp_path) == tmp_path / "tokens" / "yahoo.json"


def test_missing_app_credentials(tmp_path: Path) -> None:
    with pytest.raises(YahooConfigError, match="yahoo-app"):
        load_app_credentials(tmp_path)


def test_exchange_code_persists_token(tmp_path: Path) -> None:
    _write_app(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        return httpx.Response(
            200,
            json={
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "expires_in": 3600,
                "token_type": "bearer",
            },
        )

    with _client(tmp_path, handler) as client:
        path = client.authorize("the-code")
    stored = load_tokens(tmp_path)
    assert path == token_path(tmp_path)
    assert stored.access_token == "access-new"
    assert stored.refresh_token == "refresh-new"
    assert stored.expires_at == 4600.0


def test_refresh_after_expiry_writes_new_token(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path, expires_at=500.0)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == TOKEN_URL:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-refreshed",
                    "refresh_token": "refresh-rotated",
                    "expires_in": 3600,
                },
            )
        auth = request.headers["Authorization"]
        assert auth == "Bearer access-refreshed"
        return httpx.Response(200, json=OWN_TEAM)

    with _client(tmp_path, handler, clock=lambda: 1_000.0) as client:
        team = client.own_team()
    assert team["team_key"] == "461.l.99999.t.1"
    assert team["league_key"] == "461.l.99999"
    stored = load_tokens(tmp_path)
    assert stored.access_token == "access-refreshed"
    assert stored.refresh_token == "refresh-rotated"
    assert TOKEN_URL in seen


def test_needs_refresh_uses_skew() -> None:
    tokens = TokenSet("a", "r", expires_at=1050.0)
    assert needs_refresh(tokens, clock=lambda: 1000.0, skew=60.0) is True
    assert needs_refresh(tokens, clock=lambda: 980.0, skew=60.0) is False


def test_fantasy_401_refreshes_once_then_succeeds(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path)
    fantasy_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fantasy_calls
        if str(request.url) == TOKEN_URL:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-refreshed",
                    "refresh_token": "refresh-rotated",
                    "expires_in": 3600,
                },
            )
        fantasy_calls += 1
        if request.headers["Authorization"] == "Bearer access-old":
            return httpx.Response(401, text="unauthorized")
        assert request.headers["Authorization"] == "Bearer access-refreshed"
        return httpx.Response(200, json=OWN_TEAM)

    with _client(tmp_path, handler) as client:
        team = client.own_team()
    assert team["team_key"] == "461.l.99999.t.1"
    assert fantasy_calls == 2
    assert load_tokens(tmp_path).access_token == "access-refreshed"


def test_401_after_refresh_is_auth_error_never_swallowed(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            return httpx.Response(
                200,
                json={
                    "access_token": "access-refreshed",
                    "refresh_token": "refresh-rotated",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(401, text="unauthorized")

    with _client(tmp_path, handler) as client:
        with pytest.raises(YahooAuthError, match="browser"):
            client.own_team()


def test_refresh_invalid_grant_is_auth_error(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path, expires_at=1.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with _client(tmp_path, handler) as client:
        with pytest.raises(YahooAuthError, match="unattended"):
            client.own_team()


def test_403_access_program_is_not_auth_error(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "description": (
                        "This application is not authorized to perform this action."
                    )
                }
            },
        )

    with _client(tmp_path, handler) as client:
        with pytest.raises(YahooAPIError, match="access program"):
            client.own_team()


def test_additional_authorization_required(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='OAuth oauth_problem="additional_authorization_required"',
        )

    with _client(tmp_path, handler) as client:
        with pytest.raises(YahooAPIError, match="sports.yahoo.com/developer/access"):
            client.own_team()


def test_smoke_reads_team_settings_roster(tmp_path: Path) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/users;" in url:
            return httpx.Response(200, json=OWN_TEAM)
        if "/settings" in url:
            assert "461.l.99999" in url
            return httpx.Response(200, json=SETTINGS)
        if "/roster" in url:
            assert "461.l.99999.t.1" in url
            return httpx.Response(200, json=ROSTER)
        raise AssertionError(url)

    with _client(tmp_path, handler) as client:
        result = client.smoke()
    assert result["team_key"] == "461.l.99999.t.1"
    assert result["league_key"] == "461.l.99999"
    assert result["num_teams"] == 10
    assert result["roster_count"] == 2
    assert result["roster_position_count"] == 2
    assert result["scoring_stat_count"] == 2


def test_cli_authorize_writes_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_app(tmp_path)
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "cli-access",
                "refresh_token": "cli-refresh",
                "expires_in": 3600,
            },
        )

    def fake_client(root: Path, http=None, clock=None):
        return _client(root, handler)

    monkeypatch.setattr("yahoo.__main__.YahooClient", fake_client)
    assert main(["authorize", "--code", "abc"]) == 0
    assert load_tokens(tmp_path).access_token == "cli-access"


def test_league_key_is_derived_not_hardcoded() -> None:
    parsed = parse_own_team(
        {"team": [[{"team_key": "999.l.42.t.7"}, {"team_id": "7"}]]}
    )
    assert parsed["league_key"] == "999.l.42"
    assert league_key_from_team_key("999.l.42.t.7") == "999.l.42"


def test_multiple_nfl_teams_fail_closed() -> None:
    payload = {
        "teams": {
            "0": {"team": [[{"team_key": "461.l.1.t.1"}]]},
            "1": {"team": [[{"team_key": "461.l.2.t.3"}]]},
        }
    }
    with pytest.raises(YahooAPIError, match="refuse to guess"):
        parse_own_team(payload)


def test_refresh_persist_failure_is_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_app(tmp_path)
    _write_token(tmp_path, expires_at=1.0)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "access-refreshed",
                "refresh_token": "refresh-rotated",
                "expires_in": 3600,
            },
        )

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("yahoo.client.save_tokens", boom)
    with _client(tmp_path, handler) as client:
        with pytest.raises(YahooAuthError, match="could not be written"):
            client.own_team()

"""Authenticated Yahoo Fantasy API v2 reads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from yahoo.errors import YahooAPIError, YahooAuthError
from yahoo.oauth import exchange_code, needs_refresh, refresh_tokens
from yahoo.parse import parse_league_settings, parse_own_team, parse_roster
from yahoo.tokens import (
    AppCredentials,
    TokenSet,
    load_app_credentials,
    load_tokens,
    save_tokens,
)

FANTASY_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
OWN_TEAM_PATH = "/users;use_login=1/games;game_keys=nfl/teams"
USER_AGENT = "confidently-incorrect/0.1"


def _default_http() -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


class YahooClient:
    """Load tokens from the state volume, refresh unattended, read Fantasy v2."""

    def __init__(
        self,
        state_dir: Path,
        http: httpx.Client | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._http = http or _default_http()
        self._owns_http = http is None
        self._clock = clock
        self._creds: AppCredentials | None = None
        self._tokens: TokenSet | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> YahooClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def authorize(self, code: str) -> Path:
        creds = self._app_credentials()
        tokens = exchange_code(creds, code, self._http, clock=self._clock)
        return save_tokens(tokens, self._state_dir)

    def verify_auth(self) -> dict[str, str]:
        """Hit a user-scoped endpoint before any real work (O-9)."""
        return self.own_team()

    def own_team(self) -> dict[str, str]:
        payload = self._get(OWN_TEAM_PATH)
        return parse_own_team(payload)

    def league_settings(self, league_key: str | None = None) -> dict[str, Any]:
        key = league_key or self.own_team()["league_key"]
        payload = self._get(f"/league/{key}/settings")
        parsed = parse_league_settings(payload)
        if not parsed.get("league_key"):
            parsed["league_key"] = key
        return parsed

    def roster(self, team_key: str | None = None) -> list[dict[str, str]]:
        key = team_key or self.own_team()["team_key"]
        payload = self._get(f"/team/{key}/roster")
        return parse_roster(payload)

    def smoke(self) -> dict[str, Any]:
        team = self.own_team()
        settings = self.league_settings(team["league_key"])
        players = self.roster(team["team_key"])
        return {
            "team_key": team["team_key"],
            "league_key": team["league_key"],
            "num_teams": settings.get("num_teams"),
            "roster_position_count": settings.get("roster_position_count"),
            "scoring_stat_count": settings.get("scoring_stat_count"),
            "roster_count": len(players),
        }

    def _app_credentials(self) -> AppCredentials:
        if self._creds is None:
            self._creds = load_app_credentials(self._state_dir)
        return self._creds

    def _ensure_access_token(self) -> str:
        if self._tokens is None:
            self._tokens = load_tokens(self._state_dir)
        if needs_refresh(self._tokens, clock=self._clock):
            self._tokens = refresh_tokens(
                self._app_credentials(),
                self._tokens,
                self._http,
                clock=self._clock,
            )
            save_tokens(self._tokens, self._state_dir)
        return self._tokens.access_token

    def _get(self, path: str) -> dict[str, Any]:
        token = self._ensure_access_token()
        url = f"{FANTASY_BASE}{path}"
        response = self._http.get(
            url,
            params={"format": "json"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            raise YahooAuthError(
                "Yahoo returned 401. Reauthorization requires a browser "
                "and cannot happen unattended. Run: python -m yahoo authorize."
            )
        if response.status_code == 403 or _is_access_denied(response):
            raise YahooAPIError(
                "Yahoo Fantasy API rejected this app (403 or "
                "additional_authorization_required). This is the access "
                "program, not a bad token. Apply at "
                "https://sports.yahoo.com/developer/access/ and do not "
                "delete an existing App ID. "
                f"status={response.status_code} body={response.text[:300]}"
            )
        if response.status_code != 200:
            raise YahooAPIError(
                f"Yahoo GET {path} failed: status={response.status_code} "
                f"body={response.text[:300]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise YahooAPIError(f"Yahoo GET {path} returned a non-object JSON body")
        return payload


def _is_access_denied(response: httpx.Response) -> bool:
    body = response.text.lower()
    return (
        "additional_authorization_required" in body
        or "this application is not authorized" in body
    )

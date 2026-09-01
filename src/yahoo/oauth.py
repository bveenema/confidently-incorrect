"""Yahoo OAuth 2.0: oob authorize, token exchange, unattended refresh."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from yahoo.errors import YahooAPIError, YahooAuthError
from yahoo.tokens import AppCredentials, TokenSet

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
REDIRECT_URI = "oob"
FANTASY_SCOPE = "fspt-w"
REFRESH_SKEW_SECONDS = 60.0


def _utc_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def authorize_url(client_id: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "language": "en-us",
            "scope": FANTASY_SCOPE,
        }
    )
    return f"{AUTH_URL}?{query}"


def _token_set_from_response(payload: dict[str, Any], now: float) -> TokenSet:
    try:
        expires_in = float(payload.get("expires_in", 3600))
        return TokenSet(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=now + expires_in,
            token_type=str(payload.get("token_type") or "bearer"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise YahooAPIError(f"token response missing required fields: {exc}") from exc


def _raise_token_failure(response: httpx.Response) -> None:
    status = response.status_code
    body = response.text
    lowered = body.lower()
    if status in (400, 401) or "invalid_grant" in lowered:
        raise YahooAuthError(
            "Yahoo returned an auth failure exchanging or refreshing a token. "
            "Reauthorization requires a browser and cannot happen unattended. "
            "Run: python -m yahoo authorize. "
            f"status={status} body={body[:300]}"
        )
    raise YahooAPIError(
        f"Yahoo token endpoint failed: status={status} body={body[:300]}"
    )


def exchange_code(
    creds: AppCredentials,
    code: str,
    http: httpx.Client,
    clock: Callable[[], float] | None = None,
) -> TokenSet:
    now = (clock or _utc_now)()
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        auth=(creds.client_id, creds.client_secret),
    )
    if response.status_code != 200:
        _raise_token_failure(response)
    return _token_set_from_response(response.json(), now)


def refresh_tokens(
    creds: AppCredentials,
    tokens: TokenSet,
    http: httpx.Client,
    clock: Callable[[], float] | None = None,
) -> TokenSet:
    now = (clock or _utc_now)()
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "redirect_uri": REDIRECT_URI,
            "refresh_token": tokens.refresh_token,
        },
        auth=(creds.client_id, creds.client_secret),
    )
    if response.status_code != 200:
        _raise_token_failure(response)
    payload = response.json()
    if "refresh_token" not in payload:
        payload["refresh_token"] = tokens.refresh_token
    return _token_set_from_response(payload, now)


def needs_refresh(
    tokens: TokenSet,
    clock: Callable[[], float] | None = None,
    skew: float = REFRESH_SKEW_SECONDS,
) -> bool:
    now = (clock or _utc_now)()
    return tokens.expires_at <= now + skew

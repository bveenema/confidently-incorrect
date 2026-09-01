"""Load and persist Yahoo app credentials and OAuth tokens on the volume."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yahoo.errors import YahooConfigError
from yahoo.paths import app_credentials_path, token_path, tokens_dir

_REQUIRED_APP = ("client_id", "client_secret")
_REQUIRED_TOKEN = ("access_token", "refresh_token", "expires_at")


@dataclass(frozen=True)
class AppCredentials:
    client_id: str
    client_secret: str


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "bearer"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise YahooConfigError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise YahooConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise YahooConfigError(f"{path} must contain a JSON object")
    return raw


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    tmp.replace(path)
    if os.name != "nt":
        os.chmod(path, 0o600)


def load_app_credentials(root: Path | None = None) -> AppCredentials:
    path = app_credentials_path(root)
    data = _read_json(path)
    missing = [key for key in _REQUIRED_APP if not data.get(key)]
    if missing:
        raise YahooConfigError(f"{path} missing fields: {', '.join(missing)}")
    return AppCredentials(
        client_id=str(data["client_id"]),
        client_secret=str(data["client_secret"]),
    )


def load_tokens(root: Path | None = None) -> TokenSet:
    path = token_path(root)
    data = _read_json(path)
    missing = [key for key in _REQUIRED_TOKEN if key not in data]
    if missing:
        raise YahooConfigError(f"{path} missing fields: {', '.join(missing)}")
    try:
        expires_at = float(data["expires_at"])
    except (TypeError, ValueError) as exc:
        raise YahooConfigError(f"{path} has a non-numeric expires_at") from exc
    return TokenSet(
        access_token=str(data["access_token"]),
        refresh_token=str(data["refresh_token"]),
        expires_at=expires_at,
        token_type=str(data.get("token_type") or "bearer"),
    )


def save_tokens(tokens: TokenSet, root: Path | None = None) -> Path:
    path = token_path(root)
    _atomic_write(
        path,
        {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
            "token_type": tokens.token_type,
        },
    )
    return path


def tokens_exist(root: Path | None = None) -> bool:
    return token_path(root).is_file() and app_credentials_path(root).is_file()


def ensure_tokens_dir(root: Path | None = None) -> Path:
    directory = tokens_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    return directory

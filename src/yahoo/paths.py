"""Resolve the runtime state directory. Tokens never live in the git tree."""

from __future__ import annotations

import os
from pathlib import Path

from yahoo.errors import YahooConfigError

_LINUX_DEFAULT = Path("/srv/ci")
_APP_FILENAME = "yahoo-app.json"
_TOKEN_FILENAME = "yahoo.json"


def state_dir(override: Path | None = None) -> Path:
    """Return CI_STATE_DIR, or /srv/ci when that directory exists.

    Unset CI_STATE_DIR on a workstation (no /srv/ci) is a config error,
    not a silent write into the repo.
    """
    if override is not None:
        return override
    raw = os.environ.get("CI_STATE_DIR")
    if raw:
        return Path(raw)
    if _LINUX_DEFAULT.is_dir():
        return _LINUX_DEFAULT
    raise YahooConfigError(
        "CI_STATE_DIR is not set and /srv/ci does not exist. "
        "Set CI_STATE_DIR to a directory outside the git worktree."
    )


def tokens_dir(root: Path | None = None) -> Path:
    return state_dir(root) / "tokens"


def app_credentials_path(root: Path | None = None) -> Path:
    return tokens_dir(root) / _APP_FILENAME


def token_path(root: Path | None = None) -> Path:
    return tokens_dir(root) / _TOKEN_FILENAME

"""Resolve OpenRouter credentials on an explicit state root."""

from __future__ import annotations

import os
from pathlib import Path

from council.errors import CouncilConfigError

_LINUX_DEFAULT = Path("/srv/ci")
_CREDENTIALS_NAME = "openrouter.json"
_PLACEHOLDER = "REPLACE_ME"
TEMPLATE_HINT = (
    "Copy templates/openrouter.json to $CI_STATE_DIR/tokens/openrouter.json "
    "and replace api_key."
)


def state_dir(override: Path | None = None) -> Path:
    """Return CI_STATE_DIR, or /srv/ci when that directory exists."""
    if override is not None:
        return override
    raw = os.environ.get("CI_STATE_DIR")
    if raw:
        return Path(raw)
    if _LINUX_DEFAULT.is_dir():
        return _LINUX_DEFAULT
    raise CouncilConfigError(
        "CI_STATE_DIR is not set and /srv/ci does not exist. "
        "Set CI_STATE_DIR to a directory outside the git worktree. " + TEMPLATE_HINT
    )


def credentials_path(root: Path | None = None) -> Path:
    return state_dir(root) / "tokens" / _CREDENTIALS_NAME

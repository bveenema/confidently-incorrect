"""Resolve kb.db on an explicit state root. Library callers pass a Path."""

from __future__ import annotations

import os
from pathlib import Path

from db.errors import DbConfigError

_FILENAME = "kb.db"
_LINUX_DEFAULT = Path("/srv/ci")
_HINT = (
    "Set CI_STATE_DIR to a directory outside the git worktree, then "
    "run python -m db migrate. Tests and rehearsal must pass an "
    "explicit --state-dir (D-90)."
)


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
    raise DbConfigError("CI_STATE_DIR is not set and /srv/ci does not exist. " + _HINT)


def db_path(root: Path) -> Path:
    """Return {root}/kb.db. root is required; this never reads the env."""
    return root / _FILENAME

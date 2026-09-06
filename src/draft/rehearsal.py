"""Rehearsal --state-dir must not resolve to the live runtime root (D-92)."""

from __future__ import annotations

import os
from pathlib import Path

from draft.errors import DraftConfigError

_LINUX_DEFAULT = Path("/srv/ci")


def live_runtime_root() -> Path | None:
    """Path of the operator runtime store, or None if it cannot be resolved.

    Compares paths only. Does not read files under the live root (D-90).
    """
    raw = os.environ.get("CI_STATE_DIR")
    if raw:
        return Path(raw)
    if _LINUX_DEFAULT.is_dir():
        return _LINUX_DEFAULT
    return None


def same_root(left: Path, right: Path) -> bool:
    a = left.expanduser()
    b = right.expanduser()
    try:
        resolved_a = a.resolve()
        resolved_b = b.resolve()
    except OSError:
        return False
    if resolved_a == resolved_b:
        return True
    try:
        return (
            resolved_a.exists()
            and resolved_b.exists()
            and resolved_a.samefile(resolved_b)
        )
    except OSError:
        return False


def rehearsal_root(requested: Path) -> Path:
    """Accept a rehearsal state dir, or raise if it is the live root."""
    live = live_runtime_root()
    if live is not None and same_root(requested, live):
        raise DraftConfigError(
            f"rehearsal --state-dir {requested} resolves to the live "
            "runtime root. Point it at a temp directory so mock writes "
            "cannot contaminate kb.db (D-92)."
        )
    return requested

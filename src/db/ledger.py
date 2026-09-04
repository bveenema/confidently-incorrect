"""Open and migrate kb.db. Callers pass an explicit state root (D-90)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db.errors import DbConfigError
from db.paths import db_path

_SCHEMA_NAME = "schema.sql"
_BUSY_TIMEOUT_MS = 5000
_USER_VERSION = 1


def _schema_sql() -> str:
    path = Path(__file__).with_name(_SCHEMA_NAME)
    if not path.is_file():
        raise DbConfigError(
            f"missing schema file {path}. Reinstall the package so "
            "schema.sql ships next to the db module."
        )
    return path.read_text(encoding="utf-8")


def connect(root: Path) -> sqlite3.Connection:
    """Open {root}/kb.db in WAL mode with foreign keys on.

    Each caller (including each specialist thread) opens its own
    connection. busy_timeout lets parallel writes wait instead of
    raising SQLITE_BUSY.
    """
    path = db_path(root)
    try:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    except sqlite3.Error as exc:
        raise DbConfigError(f"failed to open {path}: {exc}") from exc
    return conn


def migrate(root: Path) -> Path:
    """Create {root}/kb.db and apply schema.sql. Idempotent for v1.

    mkdir only the given root. Never resolves CI_STATE_DIR. Does not
    ALTER an existing database; a later schema bump needs a new
    migration path.
    """
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DbConfigError(f"cannot create state dir {root}: {exc}") from exc
    path = db_path(root)
    try:
        with connect(root) as conn:
            conn.executescript(_schema_sql())
            conn.execute(f"PRAGMA user_version={_USER_VERSION}")
    except sqlite3.Error as exc:
        raise DbConfigError(f"failed to migrate {path}: {exc}") from exc
    return path

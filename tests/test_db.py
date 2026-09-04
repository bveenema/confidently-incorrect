from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from db import DbConfigError, connect, db_path, migrate
from db.__main__ import main
from db.paths import state_dir

REQUIRED_TABLES = {
    "seasons",
    "runs",
    "briefs",
    "considered_options",
    "decisions",
    "outcomes",
    "attributions",
    "executions",
    "deploys",
    "config_changes",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def test_db_path_is_under_explicit_root(tmp_path: Path) -> None:
    assert db_path(tmp_path) == tmp_path / "kb.db"


def test_migrate_creates_tables_and_season_id_columns(tmp_path: Path) -> None:
    path = migrate(tmp_path)
    assert path == tmp_path / "kb.db"
    assert path.is_file()
    with connect(tmp_path) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert REQUIRED_TABLES <= names
        assert "season_id" in _columns(conn, "runs")
        assert "season_id" in _columns(conn, "deploys")
        assert "season_id" in _columns(conn, "config_changes")
        assert "failure_mode" in _columns(conn, "runs")
        assert "publish_approved" in _columns(conn, "runs")
        assert "publish_denied_reason" in _columns(conn, "runs")
        assert "manual_intervention" in _columns(conn, "runs")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    first = migrate(tmp_path)
    second = migrate(tmp_path)
    assert first == second
    with connect(tmp_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert REQUIRED_TABLES <= tables


def test_wal_mode(tmp_path: Path) -> None:
    migrate(tmp_path)
    with connect(tmp_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


def test_failed_run_is_a_row(tmp_path: Path) -> None:
    migrate(tmp_path)
    with connect(tmp_path) as conn:
        conn.execute(
            "INSERT INTO seasons (season_id) VALUES (?)",
            ("2026",),
        )
        conn.execute(
            """
            INSERT INTO runs (season_id, ts, decision_type, failure_mode)
            VALUES (?, ?, ?, ?)
            """,
            ("2026", "2026-09-04T12:00:00-04:00", "draft", "gm_timeout"),
        )
        conn.execute(
            """
            INSERT INTO runs (season_id, ts, decision_type)
            VALUES (?, ?, ?)
            """,
            ("2026", "2026-09-04T12:01:00-04:00", "draft"),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT failure_mode, publish_approved FROM runs ORDER BY id"
        ).fetchall()
    assert rows[0] == ("gm_timeout", 0)
    assert rows[1] == (None, 0)


def test_parallel_specialist_writes(tmp_path: Path) -> None:
    migrate(tmp_path)
    with connect(tmp_path) as conn:
        conn.execute("INSERT INTO seasons (season_id) VALUES ('2026')")
        conn.execute(
            """
            INSERT INTO runs (season_id, ts, decision_type)
            VALUES ('2026', '2026-09-04T12:00:00-04:00', 'draft')
            """
        )
        run_id = conn.execute("SELECT id FROM runs").fetchone()[0]
        conn.commit()

    def _write(persona: str) -> None:
        with connect(tmp_path) as inner:
            inner.execute(
                """
                INSERT INTO briefs (run_id, persona, reasoning)
                VALUES (?, ?, ?)
                """,
                (run_id, persona, "ok"),
            )
            inner.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_write, ("belichuk", "brand", "taco", "maddox")))

    with connect(tmp_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
    assert count == 4


def test_cli_migrate_state_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["migrate", "--state-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("ok:")
    assert "kb.db" in out
    assert (tmp_path / "kb.db").is_file()


def test_cli_migrate_from_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CI_STATE_DIR", str(tmp_path))
    assert main(["migrate"]) == 0
    out = capsys.readouterr().out
    assert str(tmp_path / "kb.db") in out.replace("\\", "/") or "kb.db" in out


def test_unset_ci_state_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI_STATE_DIR", raising=False)
    monkeypatch.setattr("db.paths._LINUX_DEFAULT", Path("/nonexistent-ci-state"))
    with pytest.raises(DbConfigError, match="CI_STATE_DIR"):
        state_dir()

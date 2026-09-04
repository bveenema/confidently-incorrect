"""CLI: apply the kb.db schema on the state volume."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from db.errors import DbError
from db.ledger import migrate
from db.paths import state_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m db")
    sub = parser.add_subparsers(dest="command", required=True)
    migrate_cmd = sub.add_parser(
        "migrate",
        help="create $CI_STATE_DIR/kb.db and apply the ledger schema",
    )
    migrate_cmd.add_argument(
        "--state-dir",
        type=Path,
        help="state directory (default: $CI_STATE_DIR or /srv/ci)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "migrate":
        return _migrate(args.state_dir)
    print(f"error: unknown command {args.command!r}", file=sys.stderr)
    return 2


def _migrate(override: Path | None) -> int:
    try:
        root = state_dir(override)
        path = migrate(root)
    except DbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

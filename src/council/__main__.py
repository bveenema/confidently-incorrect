"""CLI: run one council pass against a packet and write kb.db."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from council.errors import CouncilError
from council.orchestrator import CouncilResult, run_council
from council.paths import state_dir
from council.schema import DECISION_TYPES


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m council")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser(
        "run",
        help="parallel specialists + GM; write runs and briefs to kb.db",
    )
    run.add_argument(
        "--packet",
        type=Path,
        required=True,
        help="JSON decision packet (no real manager names)",
    )
    run.add_argument(
        "--pool",
        type=Path,
        required=True,
        help='JSON array of player keys, or {"player_keys": [...]}',
    )
    run.add_argument(
        "--decision-type",
        default="draft",
        choices=sorted(DECISION_TYPES),
    )
    run.add_argument(
        "--season",
        default="",
        help="season_id (default: current year in America/New_York)",
    )
    run.add_argument(
        "--state-dir",
        type=Path,
        help="state directory (default: $CI_STATE_DIR or /srv/ci)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "run":
        return _run(
            args.packet,
            args.pool,
            args.decision_type,
            args.season,
            args.state_dir,
        )
    print(f"error: unknown command {args.command!r}", file=sys.stderr)
    return 2


def _run(
    packet_path: Path,
    pool_path: Path,
    decision_type: str,
    season: str,
    override: Path | None,
) -> int:
    try:
        root = state_dir(override)
        packet = _load_json(packet_path)
        if not isinstance(packet, dict):
            raise CouncilError(f"{packet_path} must contain a JSON object")
        pool = _load_pool(pool_path)
        season_id = season.strip() or str(
            datetime.now(ZoneInfo("America/New_York")).year
        )
        result = run_council(
            state_dir=root,
            packet=packet,
            pool=pool,
            decision_type=decision_type,
            season_id=season_id,
        )
    except CouncilError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_ok(result)
    return 0


def _print_ok(result: CouncilResult) -> None:
    adopted = ""
    if result.decision is not None:
        adopted = ",".join(result.decision.adopted_from)
    absent = ",".join(result.absent) or "-"
    print(
        f"ok: run {result.run_id} {result.decision_type} "
        f"briefs={len(result.briefs)} absent={absent} "
        f"adopted={adopted or '-'}"
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise CouncilError(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CouncilError(f"invalid JSON in {path}: {exc}") from exc


def _load_pool(path: Path) -> list[str]:
    raw = _load_json(path)
    if isinstance(raw, list):
        keys = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
        if keys:
            return keys
        raise CouncilError(f"{path} is an empty player-key list")
    if isinstance(raw, dict):
        listed = raw.get("player_keys")
        if isinstance(listed, list):
            keys = [
                item.strip()
                for item in listed
                if isinstance(item, str) and item.strip()
            ]
            if keys:
                return keys
    raise CouncilError(
        f"{path} must be a JSON array of player keys or "
        'an object with a "player_keys" array'
    )


if __name__ == "__main__":
    sys.exit(main())

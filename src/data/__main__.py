"""CLI: validate $CI_STATE_DIR/league-settings.json."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from data.errors import LeagueSettingsError
from data.league_settings import load_league_settings, load_league_settings_file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser(
        "validate-league-settings",
        help="validate $CI_STATE_DIR/league-settings.json (or --path)",
    )
    validate.add_argument(
        "--path",
        type=Path,
        help="settings file (default: $CI_STATE_DIR/league-settings.json)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        settings = (
            load_league_settings_file(args.path)
            if args.path is not None
            else load_league_settings()
        )
    except LeagueSettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    slot_count = sum(slot.count for slot in settings.roster_slots)
    print(
        f"ok: {settings.source_path} "
        f"({settings.team_count} teams, {slot_count} roster slots, "
        f"{len(settings.scoring.categories)} scoring categories)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

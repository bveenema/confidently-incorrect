"""CLI: league settings and FantasyPros smoke."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data.errors import DataError, LeagueSettingsError
from data.fantasypros import ATTRIBUTION, FantasyProsClient, state_dir
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
    smoke = sub.add_parser(
        "fantasypros-smoke",
        help="live FantasyPros read: projections, rankings, injuries, news",
    )
    smoke.add_argument(
        "--season",
        type=int,
        default=0,
        help="NFL season year (default: current year in America/New_York)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "validate-league-settings":
        return _validate_league_settings(args.path)
    return _fantasypros_smoke(args.season)


def _validate_league_settings(path: Path | None) -> int:
    try:
        settings = (
            load_league_settings_file(path)
            if path is not None
            else load_league_settings()
        )
    except LeagueSettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    slot_count = sum(slot.count for slot in settings.roster_slots)
    print(
        f"ok: {settings.source_path} "
        f"({settings.team_count} teams, {slot_count} roster slots, "
        f"{len(settings.scoring.categories)} scoring categories, "
        f"fractional_points={str(settings.scoring.fractional_points).lower()})"
    )
    return 0


def _fantasypros_smoke(season: int) -> int:
    year = season or datetime.now(ZoneInfo("America/New_York")).year
    try:
        with FantasyProsClient(state_dir()) as client:
            result = client.smoke(year)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"ok: week0={result['week0_count']} "
        f"week1_qb={result['week1_qb_count']} "
        f"rankings={result['rankings_count']} "
        f"rank_std={result['rank_std_sample']} "
        f"injuries={result['injuries_count']} "
        f"news={result['news_count']}"
    )
    print(ATTRIBUTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())

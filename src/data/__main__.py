"""CLI: league settings, FantasyPros smoke, Tank01 smoke."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data.errors import DataError, LeagueSettingsError
from data.fantasypros import ATTRIBUTION, FantasyProsClient
from data.fantasypros import state_dir as fantasypros_state_dir
from data.league_settings import load_league_settings, load_league_settings_file
from data.tank01 import ATTRIBUTION as TANK01_ATTRIBUTION
from data.tank01 import Tank01Client
from data.tank01 import state_dir as tank01_state_dir


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
    tank = sub.add_parser(
        "tank01-smoke",
        help="live Tank01 read: projections, injuries, news, implied totals",
    )
    tank.add_argument(
        "--odds-date",
        default="",
        help="YYYYMMDD for betting odds (default: today America/New_York)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "validate-league-settings":
        return _validate_league_settings(args.path)
    if args.command == "fantasypros-smoke":
        return _fantasypros_smoke(args.season)
    if args.command == "tank01-smoke":
        return _tank01_smoke(args.odds_date)
    print(f"error: unknown command {args.command!r}", file=sys.stderr)
    return 2


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
        with FantasyProsClient(fantasypros_state_dir()) as client:
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


def _tank01_smoke(odds_date: str) -> int:
    day = odds_date or datetime.now(ZoneInfo("America/New_York")).strftime("%Y%m%d")
    try:
        with Tank01Client(tank01_state_dir()) as client:
            result = client.smoke(odds_date=day)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"ok: season={result['season_count']} "
        f"week1={result['week1_count']} "
        f"dst_week1={result['week1_dst_count']} "
        f"sample_qb_pass_yd={result['sample_qb_pass_yd']} "
        f"injuries={result['injuries_count']} "
        f"news={result['news_count']} "
        f"implied_totals={result['implied_totals_count']} "
        f"odds_date={result['odds_date']}"
    )
    print(TANK01_ATTRIBUTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())

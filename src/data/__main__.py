"""CLI: league settings, provider smokes, player pool, pre-rank sheet."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data.errors import DataConfigError, DataError, LeagueSettingsError
from data.fantasypros import ATTRIBUTION, FantasyProsClient
from data.fantasypros import state_dir as fantasypros_state_dir
from data.league_settings import load_league_settings, load_league_settings_file
from data.league_settings import state_dir as league_state_dir
from data.pool import (
    PlayerPool,
    PooledPlayer,
    load_player_pool,
    load_pool_snapshot,
    pool_snapshot_path,
)
from data.prerank import DEFAULT_LIMIT, format_prerank, select_prerank
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
    pool = sub.add_parser(
        "player-pool",
        help="merge sources, score, tier, and print ADP delta",
    )
    pool.add_argument(
        "--season",
        type=int,
        default=0,
        help="NFL season year (default: current year in America/New_York)",
    )
    prerank = sub.add_parser(
        "pre-rank",
        help="top ~200 by league scoring for Yahoo pre-rank entry",
    )
    prerank.add_argument(
        "--season",
        type=int,
        default=0,
        help="NFL season year (default: current year in America/New_York)",
    )
    prerank.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"how many ranked players to list (default: {DEFAULT_LIMIT})",
    )
    prerank.add_argument(
        "--pool",
        type=Path,
        help="player-pool.json snapshot (default: $CI_STATE_DIR/player-pool.json)",
    )
    prerank.add_argument(
        "--out",
        type=Path,
        help="write the sheet to this file (default: stdout)",
    )
    prerank.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild from live APIs instead of using a snapshot",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "validate-league-settings":
        return _validate_league_settings(args.path)
    if args.command == "fantasypros-smoke":
        return _fantasypros_smoke(args.season)
    if args.command == "tank01-smoke":
        return _tank01_smoke(args.odds_date)
    if args.command == "player-pool":
        return _player_pool(args.season)
    if args.command == "pre-rank":
        return _pre_rank(args.season, args.limit, args.pool, args.out, args.refresh)
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


def _player_pool(season: int) -> int:
    year = season or datetime.now(ZoneInfo("America/New_York")).year
    try:
        settings = load_league_settings()
        with (
            FantasyProsClient(fantasypros_state_dir()) as fp,
            Tank01Client(tank01_state_dir()) as tank,
        ):
            pool = load_player_pool(settings, fp, tank, season=year)
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_player_pool(pool))
    print(ATTRIBUTION)
    print(TANK01_ATTRIBUTION)
    return 0


def _pre_rank(
    season: int,
    limit: int,
    pool_path: Path | None,
    out: Path | None,
    refresh: bool,
) -> int:
    year = season or datetime.now(ZoneInfo("America/New_York")).year
    try:
        pool = _resolve_prerank_pool(year, pool_path, refresh)
        rows = select_prerank(pool, limit)
        text = format_prerank(rows)
        if out is None:
            print(text)
            return 0
        try:
            out.write_text(text + "\n", encoding="utf-8")
        except OSError as exc:
            raise DataConfigError(f"failed writing {out}: {exc}") from exc
    except DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    omitted = sum(1 for player in pool.players if player.scoring_incomplete)
    print(
        f"ok: wrote {out} ({len(rows)} players, "
        f"season={pool.season} omitted_incomplete={omitted})"
    )
    return 0


def _resolve_prerank_pool(
    season: int, pool_path: Path | None, refresh: bool
) -> PlayerPool:
    if not refresh:
        if pool_path is not None:
            return load_pool_snapshot(pool_path)
        snap = pool_snapshot_path(league_state_dir())
        if snap.exists():
            return load_pool_snapshot(snap)
    settings = load_league_settings()
    with (
        FantasyProsClient(fantasypros_state_dir()) as fp,
        Tank01Client(tank01_state_dir()) as tank,
    ):
        return load_player_pool(settings, fp, tank, season=season)


def format_player_pool(pool: PlayerPool) -> str:
    """Human-readable board: ranks, tiers, ADP gaps, QB sanity."""
    players = pool.players
    incomplete = sum(1 for p in players if p.scoring_incomplete)
    unmatched_fp = sum(1 for p in players if p.join == "fp_only")
    unmatched_tank = sum(1 for p in players if p.join == "tank_only")
    lines = [
        f"ok: season={pool.season} players={len(players)} "
        f"adp_scoring={pool.adp_scoring} incomplete={incomplete} "
        f"fp_only={unmatched_fp} tank_only={unmatched_tank}",
        "",
        "value rank (primary FantasyPros points)",
        _header(),
    ]
    for row in pool.by_value_rank()[:15]:
        lines.append(_row(row))
    lines.extend(["", "positional tiers"])
    for position in ("QB", "RB", "WR", "TE"):
        group = pool.positional_tiers(position)
        if not group:
            continue
        lines.append(f"  {position}")
        for row in group[:12]:
            marker = "  <-- tier break" if row.tier_break_after else ""
            flag = " [incomplete]" if row.scoring_incomplete else ""
            lines.append(
                f"    T{row.tier} #{row.pos_rank} {row.name} "
                f"fp={_pts(row.fp_points)}{flag}{marker}"
            )
    lines.extend(["", "ADP gaps (market later than us; complete lines only)"])
    for row in pool.by_adp_gap()[:20]:
        lines.append(
            f"  {row.name} {row.position} value=#{row.value_rank} "
            f"adp={_pts(row.adp)} gap={_pts(row.adp_delta)} "
            f"fp={_pts(row.fp_points)} tank={_pts(row.tank_points)} "
            f"d={_pts(row.source_delta)}"
        )
    check = pool.qb_inflation
    status = "PASS" if check.ok else "FAIL"
    lines.extend(
        [
            "",
            f"QB inflation {status}: {check.detail}",
        ]
    )
    for row in check.top_qbs:
        lines.append(
            f"  {row.name} value=#{row.value_rank} adp={_pts(row.adp)} "
            f"gap={_pts(row.adp_delta)} fp={_pts(row.fp_points)}"
        )
    if not check.ok:
        lines.append(
            "  if this fails on live data, the scoring engine or ADP join is wrong"
        )
    return "\n".join(lines)


def _header() -> str:
    return (
        f"{'#':>3} {'name':<22} {'pos':<3} {'fp':>5} {'tank':>5} "
        f"{'d':>5} {'adp':>6} {'gap':>6} {'tier':>4}"
    )


def _row(player: PooledPlayer) -> str:
    return (
        f"{player.value_rank or '-':>3} "
        f"{player.name[:22]:<22} "
        f"{player.position:<3} "
        f"{_pts(player.fp_points):>5} "
        f"{_pts(player.tank_points):>5} "
        f"{_pts(player.source_delta):>5} "
        f"{_pts(player.adp):>6} "
        f"{_pts(player.adp_delta):>6} "
        f"{player.tier or '-':>4}"
    )


def _pts(value: int | float | None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


if __name__ == "__main__":
    sys.exit(main())

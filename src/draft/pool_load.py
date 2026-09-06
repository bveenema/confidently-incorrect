"""Load the player pool for draft night: snapshot first, live as fallback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from data import DataError
from data.fantasypros import FantasyProsClient
from data.fantasypros import state_dir as fantasypros_state_dir
from data.league_settings import LeagueSettings
from data.pool import PlayerPool, load_player_pool, pool_snapshot_path
from data.tank01 import Tank01Client
from data.tank01 import state_dir as tank01_state_dir
from draft.errors import DraftConfigError
from draft.io import load_pool_snapshot, save_pool_snapshot


def load_draft_pool(
    root: Path,
    settings: LeagueSettings,
    *,
    season: int = 0,
    refresh: bool = False,
) -> PlayerPool:
    if season:
        year = season
    else:
        try:
            year = datetime.now(ZoneInfo("America/New_York")).year
        except ZoneInfoNotFoundError as exc:
            raise DraftConfigError(
                "could not resolve America/New_York; install the tzdata package "
                f"(pip install tzdata). Underlying error: {exc}"
            ) from exc
    snap = pool_snapshot_path(root)
    if snap.exists() and not refresh:
        print(f"using snapshot {snap}", flush=True)
        return load_pool_snapshot(snap)
    print(
        "building player pool from FantasyPros + Tank01 "
        "(first boot; may take a minute)...",
        flush=True,
    )
    try:
        with (
            FantasyProsClient(fantasypros_state_dir(root)) as fp,
            Tank01Client(tank01_state_dir(root)) as tank,
        ):
            pool = load_player_pool(settings, fp, tank, season=year)
    except DataError as exc:
        if snap.exists() and not refresh:
            return load_pool_snapshot(snap)
        raise DraftConfigError(
            "could not build the player pool"
            + ("" if refresh else f" and no snapshot at {snap}")
            + f": {exc}"
        ) from exc
    save_pool_snapshot(snap, pool)
    print(f"wrote snapshot {snap} ({len(pool.players)} players)", flush=True)
    return pool

"""Load the player pool for draft night: snapshot first, live as fallback."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data import DataError
from data.fantasypros import FantasyProsClient
from data.fantasypros import state_dir as fantasypros_state_dir
from data.league_settings import LeagueSettings
from data.pool import PlayerPool, load_player_pool
from data.tank01 import Tank01Client
from data.tank01 import state_dir as tank01_state_dir
from draft.errors import DraftConfigError
from draft.io import load_pool_snapshot, pool_snapshot_path, save_pool_snapshot


def load_draft_pool(
    root: Path,
    settings: LeagueSettings,
    *,
    season: int = 0,
    refresh: bool = False,
) -> PlayerPool:
    year = season or datetime.now(ZoneInfo("America/New_York")).year
    snap = pool_snapshot_path(root)
    if snap.exists() and not refresh:
        return load_pool_snapshot(snap)
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
    return pool

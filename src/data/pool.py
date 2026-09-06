"""Merge projection sources, score, tier, and compute ADP delta.

D-88 / issue 8. FantasyPros is primary (D-20); Tank01 is the disagreement
signal. Provider point totals are never consulted (D-48 / D-84).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from data.errors import DataAPIError, DataConfigError
from data.fantasypros import ConsensusRank
from data.fantasypros import PlayerProjection as FantasyProsProjection
from data.league_settings import LeagueSettings, Scoring
from data.scoring import fantasy_points
from data.tank01 import PlayerIdentity
from data.tank01 import PlayerProjection as Tank01Projection
from data.tank01 import ProjectionSet as Tank01ProjectionSet

# Diagnostic only — not a league setting. Top QBs should clear this gap
# when completions/pass TDs inflate value versus published ADP.
_QB_GAP_FLOOR = 8.0
POOL_SNAPSHOT_SCHEMA = 1
POOL_SNAPSHOT_FILENAME = "player-pool.json"
_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
# NFL abbreviation drift, not league values.
_TEAM_CANON = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LA": "LAR",
}


@dataclass(frozen=True)
class PooledPlayer:
    name: str
    position: str
    team: str
    yahoo_id: str | None
    fpid: int | None
    tank_id: str | None
    fp_points: int | float | None
    tank_points: int | float | None
    source_delta: int | float | None
    value_rank: int | None
    pos_rank: int | None
    adp: float | None
    adp_delta: float | None
    tier: int | None
    tier_break_after: bool
    scoring_incomplete: bool
    join: str


@dataclass(frozen=True)
class QbInflationCheck:
    ok: bool
    median_gap: float | None
    top_qbs: tuple[PooledPlayer, ...]
    detail: str


@dataclass(frozen=True)
class PlayerPool:
    season: int
    adp_scoring: str
    players: tuple[PooledPlayer, ...]
    qb_inflation: QbInflationCheck

    def by_value_rank(self) -> tuple[PooledPlayer, ...]:
        ranked = [p for p in self.players if p.value_rank is not None]
        ranked.sort(key=lambda p: p.value_rank or 0)
        return tuple(ranked)

    def by_adp_gap(self) -> tuple[PooledPlayer, ...]:
        """Complete-scoring players with both ranks, largest ADP discount first."""
        rows = [
            p
            for p in self.players
            if p.adp_delta is not None and not p.scoring_incomplete
        ]
        rows.sort(key=lambda p: (-(p.adp_delta or 0.0), p.name))
        return tuple(rows)

    def positional_tiers(self, position: str) -> tuple[PooledPlayer, ...]:
        pos = normalize_position(position)
        rows = [p for p in self.players if p.position == pos and p.pos_rank is not None]
        rows.sort(key=lambda p: p.pos_rank or 0)
        return tuple(rows)


def adp_scoring_type(scoring: Scoring) -> str:
    """STD / HALF / PPR from the ingested reception category, not a constant."""
    rec = next(
        (
            cat
            for cat in scoring.categories
            if cat.stat == "rec" and cat.per is None and cat.bounds is None
        ),
        None,
    )
    if rec is None or rec.points == 0:
        return "STD"
    if rec.points >= 1:
        return "PPR"
    return "HALF"


def normalize_position(position: str) -> str:
    pos = position.strip().upper()
    if pos in {"DEF", "D/ST", "D-ST"}:
        return "DST"
    if pos == "PK":
        return "K"
    return pos


def normalize_team(team: str) -> str:
    token = team.strip().upper()
    return _TEAM_CANON.get(token, token)


def normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    parts = [part for part in cleaned.split() if part and part not in _SUFFIXES]
    return " ".join(parts)


def scoring_incomplete(
    position: str, stats: Mapping[str, Any], scoring: Scoring
) -> bool:
    """True when this position's scored slugs are missing from the stat line.

    A-13 / D-86: FantasyPros and Tank01 omit FG distance bands and DST
    return yards. Do not invent those slugs; flag the line instead.
    """
    pos = normalize_position(position)
    present = set(stats)
    slugs = {cat.stat for cat in scoring.categories}
    if pos == "K":
        bands = {slug for slug in slugs if slug.startswith("fg_")}
        return bool(bands) and bands.isdisjoint(present)
    if pos == "DST":
        if "dst_return_yd" in slugs and "dst_return_yd" not in present:
            return True
        return False
    return False


def assign_tiers(points: Sequence[float]) -> tuple[tuple[int, bool], ...]:
    """Intra-position cliffs: a break when the drop exceeds mean + sample σ."""
    count = len(points)
    if count == 0:
        return ()
    if count == 1:
        return ((1, False),)
    drops = [points[i] - points[i + 1] for i in range(count - 1)]
    mean = sum(drops) / len(drops)
    std = _sample_stdev(drops)
    threshold = mean + std
    assigned: list[tuple[int, bool]] = []
    tier = 1
    for index in range(count):
        break_after = (
            index < count - 1 and drops[index] > threshold and drops[index] > 0
        )
        assigned.append((tier, break_after))
        if break_after:
            tier += 1
    return tuple(assigned)


def build_player_pool(
    scoring: Scoring,
    fp_players: Sequence[FantasyProsProjection],
    tank: Tank01ProjectionSet,
    adp_rows: Sequence[ConsensusRank],
    identities: Sequence[PlayerIdentity],
    *,
    season: int,
) -> PlayerPool:
    scoring_label = adp_scoring_type(scoring)
    adp_by_fpid = {row.fpid: row for row in adp_rows}
    adp_by_yahoo = {
        row.yahoo_id: row for row in adp_rows if row.yahoo_id not in (None, "")
    }
    adp_by_key = {
        (
            normalize_name(row.name),
            normalize_team(row.team),
            normalize_position(row.position),
        ): row
        for row in adp_rows
    }
    identity_by_id = {row.player_id: row for row in identities}

    tank_rows = list(tank.players) + list(tank.defenses)
    tank_slots = [
        _tank_slot(row, identity_by_id.get(row.player_id)) for row in tank_rows
    ]
    tank_by_yahoo: dict[str, _SourceSlot] = {}
    tank_by_key: dict[tuple[str, str, str], _SourceSlot] = {}
    tank_dst_by_team: dict[str, _SourceSlot] = {}
    for slot in tank_slots:
        if slot.yahoo_id:
            tank_by_yahoo.setdefault(slot.yahoo_id, slot)
        tank_by_key.setdefault(slot.key, slot)
        if slot.position == "DST" and slot.team:
            tank_dst_by_team.setdefault(slot.team, slot)

    used_tank: set[int] = set()
    merged: list[PooledPlayer] = []
    for fp in fp_players:
        adp = _adp_for_fp(fp, adp_by_fpid, adp_by_key)
        yahoo_id = adp.yahoo_id if adp is not None else None
        fp_slot = _fp_slot(fp, yahoo_id)
        tank_slot, join = _match_tank(
            fp_slot, tank_by_yahoo, tank_by_key, tank_dst_by_team
        )
        if tank_slot is not None:
            used_tank.add(id(tank_slot))
            yahoo_id = yahoo_id or tank_slot.yahoo_id
        merged.append(
            _score_pair(
                scoring,
                name=fp_slot.name,
                position=fp_slot.position,
                team=fp_slot.team,
                yahoo_id=yahoo_id,
                fpid=fp.fpid,
                tank_id=tank_slot.player_id if tank_slot else None,
                fp_stats=fp.stats,
                tank_stats=tank_slot.stats if tank_slot else None,
                adp=_adp_value(adp),
                join=join,
            )
        )

    for slot in tank_slots:
        if id(slot) in used_tank:
            continue
        adp = None
        if slot.yahoo_id:
            adp = adp_by_yahoo.get(slot.yahoo_id)
        if adp is None:
            adp = adp_by_key.get(slot.key)
        merged.append(
            _score_pair(
                scoring,
                name=slot.name,
                position=slot.position,
                team=slot.team,
                yahoo_id=slot.yahoo_id or (adp.yahoo_id if adp else None),
                fpid=None,
                tank_id=slot.player_id,
                fp_stats=None,
                tank_stats=slot.stats,
                adp=_adp_value(adp),
                join="tank_only",
            )
        )

    ranked = _assign_ranks_and_tiers(merged)
    check = qb_inflation_check(ranked)
    return PlayerPool(
        season=season,
        adp_scoring=scoring_label,
        players=tuple(ranked),
        qb_inflation=check,
    )


def load_player_pool(
    settings: LeagueSettings,
    fp_client: Any,
    tank_client: Any,
    *,
    season: int,
) -> PlayerPool:
    """Fetch season-long lines + ADP and merge. Both sources are required."""
    projections = fp_client.projections(season, week=0)
    if projections.truncated:
        raise DataAPIError(
            "FantasyPros projections are truncated "
            f"({len(projections.players)}/{projections.advertised_count}). "
            "HOF production keys return the full pool."
        )
    if not projections.players:
        raise DataAPIError("FantasyPros week-0 projections returned no players")
    scoring_label = adp_scoring_type(settings.scoring)
    adp_rows = fp_client.consensus_rankings(
        season,
        position="ALL",
        scoring=scoring_label,
        ranking_type="ADP",
    )
    if not adp_rows:
        raise DataAPIError(
            "FantasyPros ADP (consensus-rankings type=ADP) returned no players"
        )
    tank = tank_client.projections(week="season")
    if not tank.players:
        raise DataAPIError("Tank01 season projections returned no players")
    identities = tank_client.player_list()
    if not identities:
        raise DataAPIError("Tank01 player_list returned no players")
    return build_player_pool(
        settings.scoring,
        projections.players,
        tank,
        adp_rows,
        identities,
        season=season,
    )


def pool_snapshot_path(root: Path) -> Path:
    return root / POOL_SNAPSHOT_FILENAME


def load_pool_snapshot(path: Path) -> PlayerPool:
    """Load a player-pool.json snapshot written by draft serve (schema 1)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise DataConfigError(f"missing player-pool snapshot: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DataConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DataConfigError(f"{path} must contain a JSON object")
    version = raw.get("schema_version")
    if version != POOL_SNAPSHOT_SCHEMA:
        raise DataConfigError(
            f"{path} has unsupported schema_version {version!r} "
            f"(expected {POOL_SNAPSHOT_SCHEMA})"
        )
    season = raw.get("season")
    adp = raw.get("adp_scoring")
    rows = raw.get("players")
    if not isinstance(season, int) or isinstance(season, bool):
        raise DataConfigError(f"{path}: season must be an integer")
    if not isinstance(adp, str) or not adp.strip():
        raise DataConfigError(f"{path}: adp_scoring must be a non-empty string")
    if not isinstance(rows, list) or not rows:
        raise DataConfigError(f"{path}: players must be a non-empty array")
    players = tuple(
        _player_from_snapshot(item, path, index) for index, item in enumerate(rows)
    )
    return PlayerPool(
        season=season,
        adp_scoring=adp,
        players=players,
        qb_inflation=QbInflationCheck(
            ok=True,
            median_gap=None,
            top_qbs=(),
            detail="loaded from snapshot",
        ),
    )


def _player_from_snapshot(item: Any, path: Path, index: int) -> PooledPlayer:
    prefix = f"{path}: players[{index}]"
    if not isinstance(item, dict):
        raise DataConfigError(f"{prefix} must be an object")
    name = item.get("name")
    position = item.get("position")
    team = item.get("team")
    if not isinstance(name, str) or not name.strip():
        raise DataConfigError(f"{prefix}.name must be a non-empty string")
    if not isinstance(position, str) or not position.strip():
        raise DataConfigError(f"{prefix}.position must be a non-empty string")
    if not isinstance(team, str) or not team.strip():
        raise DataConfigError(f"{prefix}.team must be a non-empty string")
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
        yahoo_id=_opt_str(item.get("yahoo_id")),
        fpid=_opt_int(item.get("fpid")),
        tank_id=_opt_str(item.get("tank_id")),
        fp_points=_opt_num(item.get("fp_points")),
        tank_points=_opt_num(item.get("tank_points")),
        source_delta=_opt_num(item.get("source_delta")),
        value_rank=_opt_int(item.get("value_rank")),
        pos_rank=_opt_int(item.get("pos_rank")),
        adp=_opt_num(item.get("adp")),
        adp_delta=_opt_num(item.get("adp_delta")),
        tier=_opt_int(item.get("tier")),
        tier_break_after=bool(item.get("tier_break_after", False)),
        scoring_incomplete=bool(item.get("scoring_incomplete", False)),
        join=str(item.get("join") or "snapshot"),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _opt_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _opt_num(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def qb_inflation_check(players: Sequence[PooledPlayer]) -> QbInflationCheck:
    qbs = [p for p in players if p.position == "QB" and p.fp_points is not None]
    qbs.sort(key=lambda p: (-_as_sort_points(p.fp_points), p.name))
    comparable = [p for p in qbs[:3] if p.adp is not None and p.value_rank is not None]
    if not comparable:
        return QbInflationCheck(
            ok=False,
            median_gap=None,
            top_qbs=tuple(qbs[:3]),
            detail="not enough top QBs have both a value rank and an ADP",
        )
    gaps = [(p.adp or 0.0) - (p.value_rank or 0) for p in comparable]
    gaps.sort()
    mid = len(gaps) // 2
    if len(gaps) % 2:
        median = gaps[mid]
    else:
        median = (gaps[mid - 1] + gaps[mid]) / 2.0
    ok = median >= _QB_GAP_FLOOR
    detail = (
        f"median ADP−value-rank among top {len(comparable)} QBs is {median:g} "
        f"(need ≥ {_QB_GAP_FLOOR:g})"
    )
    return QbInflationCheck(
        ok=ok,
        median_gap=median,
        top_qbs=tuple(comparable),
        detail=detail,
    )


@dataclass(frozen=True)
class _SourceSlot:
    name: str
    position: str
    team: str
    yahoo_id: str | None
    player_id: str | None
    stats: dict[str, float]
    key: tuple[str, str, str]


def _fp_slot(fp: FantasyProsProjection, yahoo_id: str | None) -> _SourceSlot:
    position = normalize_position(fp.position)
    team = normalize_team(fp.team)
    return _SourceSlot(
        name=fp.name,
        position=position,
        team=team,
        yahoo_id=yahoo_id,
        player_id=str(fp.fpid),
        stats=fp.stats,
        key=(normalize_name(fp.name), team, position),
    )


def _tank_slot(row: Tank01Projection, identity: PlayerIdentity | None) -> _SourceSlot:
    position = normalize_position(row.position)
    team = normalize_team(row.team)
    yahoo_id = identity.yahoo_id if identity is not None else None
    return _SourceSlot(
        name=row.name,
        position=position,
        team=team,
        yahoo_id=yahoo_id,
        player_id=row.player_id,
        stats=row.stats,
        key=(normalize_name(row.name), team, position),
    )


def _adp_for_fp(
    fp: FantasyProsProjection,
    by_fpid: Mapping[int, ConsensusRank],
    by_key: Mapping[tuple[str, str, str], ConsensusRank],
) -> ConsensusRank | None:
    hit = by_fpid.get(fp.fpid)
    if hit is not None:
        return hit
    key = (
        normalize_name(fp.name),
        normalize_team(fp.team),
        normalize_position(fp.position),
    )
    return by_key.get(key)


def _adp_value(row: ConsensusRank | None) -> float | None:
    if row is None:
        return None
    if row.rank_ave is not None:
        return row.rank_ave
    if row.rank_ecr is not None:
        return float(row.rank_ecr)
    return None


def _match_tank(
    fp: _SourceSlot,
    by_yahoo: Mapping[str, _SourceSlot],
    by_key: Mapping[tuple[str, str, str], _SourceSlot],
    dst_by_team: Mapping[str, _SourceSlot],
) -> tuple[_SourceSlot | None, str]:
    if fp.yahoo_id and fp.yahoo_id in by_yahoo:
        return by_yahoo[fp.yahoo_id], "yahoo_id"
    if fp.key in by_key:
        return by_key[fp.key], "name_team_pos"
    if fp.position == "DST" and fp.team in dst_by_team:
        return dst_by_team[fp.team], "team_dst"
    return None, "fp_only"


def _score_pair(
    scoring: Scoring,
    *,
    name: str,
    position: str,
    team: str,
    yahoo_id: str | None,
    fpid: int | None,
    tank_id: str | None,
    fp_stats: Mapping[str, float] | None,
    tank_stats: Mapping[str, float] | None,
    adp: float | None,
    join: str,
) -> PooledPlayer:
    fp_points = fantasy_points(scoring, fp_stats) if fp_stats is not None else None
    tank_points = (
        fantasy_points(scoring, tank_stats) if tank_stats is not None else None
    )
    source_delta: int | float | None = None
    if fp_points is not None and tank_points is not None:
        source_delta = fp_points - tank_points
    stats_for_flag = fp_stats if fp_stats is not None else tank_stats or {}
    incomplete = scoring_incomplete(position, stats_for_flag, scoring)
    return PooledPlayer(
        name=name,
        position=position,
        team=team,
        yahoo_id=yahoo_id,
        fpid=fpid,
        tank_id=tank_id,
        fp_points=fp_points,
        tank_points=tank_points,
        source_delta=source_delta,
        value_rank=None,
        pos_rank=None,
        adp=adp,
        adp_delta=None,
        tier=None,
        tier_break_after=False,
        scoring_incomplete=incomplete,
        join=join,
    )


def _assign_ranks_and_tiers(players: Sequence[PooledPlayer]) -> list[PooledPlayer]:
    with_fp = [
        p for p in players if p.fp_points is not None and not p.scoring_incomplete
    ]
    with_fp.sort(key=lambda p: (-_as_sort_points(p.fp_points), p.name))
    value_rank = {id(p): index + 1 for index, p in enumerate(with_fp)}

    by_pos: dict[str, list[PooledPlayer]] = {}
    for player in players:
        if player.fp_points is None and player.tank_points is None:
            continue
        by_pos.setdefault(player.position, []).append(player)

    pos_rank: dict[int, int] = {}
    tier_of: dict[int, int] = {}
    break_after: dict[int, bool] = {}
    for group in by_pos.values():
        group.sort(
            key=lambda p: (
                -_as_sort_points(
                    p.fp_points if p.fp_points is not None else p.tank_points
                ),
                p.name,
            )
        )
        points = [
            _as_sort_points(p.fp_points if p.fp_points is not None else p.tank_points)
            for p in group
        ]
        tiers = assign_tiers(points)
        for index, player in enumerate(group):
            pos_rank[id(player)] = index + 1
            tier_of[id(player)] = tiers[index][0]
            break_after[id(player)] = tiers[index][1]

    out: list[PooledPlayer] = []
    for player in players:
        rank = value_rank.get(id(player))
        adp_delta = None
        if player.adp is not None and rank is not None:
            adp_delta = player.adp - rank
        out.append(
            replace(
                player,
                value_rank=rank,
                pos_rank=pos_rank.get(id(player)),
                adp_delta=adp_delta,
                tier=tier_of.get(id(player)),
                tier_break_after=break_after.get(id(player), False),
            )
        )
    return out


def _as_sort_points(value: int | float | None) -> float:
    return float(value) if value is not None else 0.0


def _sample_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(variance)

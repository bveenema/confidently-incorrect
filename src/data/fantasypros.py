"""FantasyPros public v2 client: stat lines, rankings, injuries, news.

Provider point totals are dropped (D-48 / D-84). Stat keys are mapped
onto the scoring-engine slugs. Rank spread (`rank_std`) comes from
consensus rankings, not the projections payload (D-86 / D-21).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from data.errors import DataAPIError, DataConfigError

API_BASE = "https://api.fantasypros.com/public/v2/json"
ATTRIBUTION = (
    "Projections, consensus rankings, injuries, and news: FantasyPros "
    "(https://www.fantasypros.com)."
)
USER_AGENT = "confidently-incorrect/0.1"
DEFAULT_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
_LINUX_DEFAULT = Path("/srv/ci")
_CREDENTIALS_NAME = "fantasypros.json"
_PLACEHOLDER = "REPLACE_ME"
_TEMPLATE_HINT = (
    "Copy templates/fantasypros.json to $CI_STATE_DIR/tokens/fantasypros.json "
    "and replace api_key."
)

# Provider key → scoring-engine slug. Not league values — names only.
STAT_MAP = {
    "pass_cmp": "pass_cmp",
    "pass_att": "pass_att",
    "pass_yds": "pass_yd",
    "pass_tds": "pass_td",
    "pass_ints": "pass_int",
    "rush_att": "rush_att",
    "rush_yds": "rush_yd",
    "rush_tds": "rush_td",
    "rec_rec": "rec",
    "rec_yds": "rec_yd",
    "rec_tds": "rec_td",
    "fumbles": "fum_lost",
    "2pt_tds": "two_pt",
    "xpt": "pat_made",
    "def_sack": "dst_sack",
    "def_int": "dst_int",
    "def_fr": "dst_fum_rec",
    "def_td": "dst_td",
    "def_safety": "dst_safety",
    "def_pa": "dst_pts_allowed",
    "def_tyda": "dst_yds_allowed",
    # Not engine slugs — kept so issue 8 can see FG volume. No distance bands.
    "fg": "fg",
    "fga": "fga",
}


@dataclass(frozen=True)
class FantasyProsCredentials:
    api_key: str


@dataclass(frozen=True)
class PlayerProjection:
    fpid: int
    name: str
    position: str
    team: str
    stats: dict[str, float]


@dataclass(frozen=True)
class ProjectionSet:
    season: int
    week: int
    truncated: bool
    advertised_count: int
    players: tuple[PlayerProjection, ...]


@dataclass(frozen=True)
class ConsensusRank:
    fpid: int
    yahoo_id: str | None
    name: str
    position: str
    team: str
    rank_ecr: int | None
    rank_std: float | None
    rank_min: int | None
    rank_max: int | None
    tier: int | None


@dataclass(frozen=True)
class Injury:
    fpid: int
    yahoo_id: str | None
    name: str
    status: str
    injury_type: str
    comment: str
    probability_of_playing: float | None


@dataclass(frozen=True)
class NewsItem:
    item_id: int
    player_id: int | None
    title: str
    desc: str
    impact: str
    categories: tuple[str, ...]
    created: str


def state_dir(override: Path | None = None) -> Path:
    """Return CI_STATE_DIR, or /srv/ci when that directory exists."""
    if override is not None:
        return override
    raw = os.environ.get("CI_STATE_DIR")
    if raw:
        return Path(raw)
    if _LINUX_DEFAULT.is_dir():
        return _LINUX_DEFAULT
    raise DataConfigError(
        "CI_STATE_DIR is not set and /srv/ci does not exist. "
        "Set CI_STATE_DIR to a directory outside the git worktree. " + _TEMPLATE_HINT
    )


def credentials_path(root: Path | None = None) -> Path:
    return state_dir(root) / "tokens" / _CREDENTIALS_NAME


def load_credentials(root: Path | None = None) -> FantasyProsCredentials:
    path = credentials_path(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DataConfigError(f"missing file: {path}. {_TEMPLATE_HINT}") from exc
    except json.JSONDecodeError as exc:
        raise DataConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DataConfigError(f"{path} must contain a JSON object")
    key = raw.get("api_key")
    if not isinstance(key, str) or not key.strip() or key.strip() == _PLACEHOLDER:
        raise DataConfigError(f"{path} missing a real api_key. {_TEMPLATE_HINT}")
    return FantasyProsCredentials(api_key=key.strip())


def credentials_exist(root: Path | None = None) -> bool:
    try:
        load_credentials(root)
    except DataConfigError:
        return False
    return True


def map_stat_line(raw: Mapping[str, Any]) -> dict[str, float]:
    """Translate a FantasyPros stats object onto engine slugs.

    Drops every `points*` field and any key not in STAT_MAP.
    """
    mapped: dict[str, float] = {}
    for key, value in raw.items():
        if str(key).startswith("points"):
            continue
        slug = STAT_MAP.get(str(key))
        if slug is None:
            continue
        number = _as_float(value)
        if number is None:
            continue
        mapped[slug] = number
    return mapped


def _default_http() -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


class FantasyProsClient:
    """Load the API key from the state volume and read public v2 JSON."""

    def __init__(
        self,
        state_dir: Path,
        http: httpx.Client | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._http = http or _default_http()
        self._owns_http = http is None
        self._creds: FantasyProsCredentials | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> FantasyProsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def projections(
        self,
        season: int,
        *,
        week: int,
        positions: Sequence[str] | None = None,
    ) -> ProjectionSet:
        pos = tuple(positions) if positions is not None else DEFAULT_POSITIONS
        params: dict[str, str] = {"week": str(week)}
        if len(pos) == 1:
            params["position"] = pos[0]
        else:
            params["positions"] = ":".join(pos)
        payload = self._get(f"/nfl/{season}/projections", params)
        players = tuple(
            _parse_projection(row) for row in _object_list(payload, "players")
        )
        advertised = _as_int(payload.get("count"))
        if advertised is None:
            advertised = len(players)
        # HOF still sends public_api_limited=true; that flag is not a page cap.
        truncated = len(players) < advertised
        parsed_week = _as_int(payload.get("week"))
        return ProjectionSet(
            season=_as_int(payload.get("season")) or season,
            week=week if parsed_week is None else parsed_week,
            truncated=truncated,
            advertised_count=advertised,
            players=players,
        )

    def consensus_rankings(
        self,
        season: int,
        *,
        position: str,
        scoring: str,
    ) -> tuple[ConsensusRank, ...]:
        payload = self._get(
            f"/nfl/{season}/consensus-rankings",
            {"position": position, "scoring": scoring},
        )
        return tuple(_parse_rank(row) for row in _object_list(payload, "players"))

    def injuries(self) -> tuple[Injury, ...]:
        payload = self._get("/nfl/injuries", {})
        return tuple(_parse_injury(row) for row in _object_list(payload, "injuries"))

    def news(
        self,
        *,
        category: str | None = None,
        limit: int = 25,
    ) -> tuple[NewsItem, ...]:
        params: dict[str, str] = {"limit": str(limit)}
        if category:
            params["category"] = category
        payload = self._get("/nfl/news", params)
        return tuple(_parse_news(row) for row in _object_list(payload, "items"))

    def smoke(self, season: int) -> dict[str, Any]:
        """Hit projections, rankings, injuries, and news. Fail on truncation."""
        week0 = self.projections(season, week=0)
        week1 = self.projections(season, week=1, positions=("QB",))
        ranks = self.consensus_rankings(season, position="RB", scoring="PPR")
        injuries = self.injuries()
        news = self.news(category="injury", limit=3)
        if not week0.players or not week1.players:
            raise DataAPIError(
                "FantasyPros smoke got an empty projection set "
                f"(week0={len(week0.players)} week1={len(week1.players)})."
            )
        if week0.truncated or week1.truncated:
            raise DataAPIError(
                "FantasyPros response is truncated "
                f"(week0 {len(week0.players)}/{week0.advertised_count}, "
                f"week1 {len(week1.players)}/{week1.advertised_count}). "
                "HOF production keys return the full pool."
            )
        sample_std = next(
            (row.rank_std for row in ranks if row.rank_std is not None),
            None,
        )
        return {
            "attribution": ATTRIBUTION,
            "week0_count": len(week0.players),
            "week1_qb_count": len(week1.players),
            "rankings_count": len(ranks),
            "rank_std_sample": sample_std,
            "injuries_count": len(injuries),
            "news_count": len(news),
        }

    def _credentials(self) -> FantasyProsCredentials:
        if self._creds is None:
            self._creds = load_credentials(self._state_dir)
        return self._creds

    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        response = self._http.get(
            f"{API_BASE}{path}",
            params=dict(params),
            headers={"x-api-key": self._credentials().api_key},
        )
        if response.status_code != 200:
            raise DataAPIError(
                f"FantasyPros GET {path} failed: status={response.status_code}"
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DataAPIError(f"FantasyPros GET {path} returned non-JSON") from exc
        if not isinstance(payload, dict):
            raise DataAPIError(
                f"FantasyPros GET {path} returned a non-object JSON body"
            )
        return payload


def _object_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise DataAPIError(f"FantasyPros field {key!r} must be a list")
    objects: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            objects.append(row)
    return objects


def _parse_projection(row: Mapping[str, Any]) -> PlayerProjection:
    raw_id = row.get("fpid")
    if raw_id is None:
        raw_id = row.get("player_id")
    fpid = _as_int(raw_id)
    if fpid is None:
        raise DataAPIError("projection row missing fpid")
    stats = row.get("stats")
    mapped = map_stat_line(stats) if isinstance(stats, dict) else {}
    return PlayerProjection(
        fpid=fpid,
        name=str(row.get("name") or row.get("player_name") or ""),
        position=str(row.get("position_id") or row.get("player_position_id") or ""),
        team=str(row.get("team_id") or row.get("player_team_id") or ""),
        stats=mapped,
    )


def _parse_rank(row: Mapping[str, Any]) -> ConsensusRank:
    raw_id = row.get("player_id")
    if raw_id is None:
        raw_id = row.get("fpid")
    fpid = _as_int(raw_id)
    if fpid is None:
        raise DataAPIError("ranking row missing player_id")
    yahoo = row.get("player_yahoo_id")
    if yahoo is None:
        yahoo = row.get("yahoo_id")
    return ConsensusRank(
        fpid=fpid,
        yahoo_id=str(yahoo) if yahoo not in (None, "") else None,
        name=str(row.get("player_name") or row.get("name") or ""),
        position=str(row.get("player_position_id") or row.get("position_id") or ""),
        team=str(row.get("player_team_id") or row.get("team_id") or ""),
        rank_ecr=_as_int(row.get("rank_ecr")),
        rank_std=_as_float(row.get("rank_std")),
        rank_min=_as_int(row.get("rank_min")),
        rank_max=_as_int(row.get("rank_max")),
        tier=_as_int(row.get("tier")),
    )


def _parse_injury(row: Mapping[str, Any]) -> Injury:
    fpid = _as_int(row.get("player_id"))
    if fpid is None:
        raise DataAPIError("injury row missing player_id")
    yahoo = row.get("yahoo_id")
    return Injury(
        fpid=fpid,
        yahoo_id=str(yahoo) if yahoo not in (None, "") else None,
        name=str(row.get("name") or ""),
        status=str(row.get("status") or ""),
        injury_type=str(row.get("injury_type") or ""),
        comment=str(row.get("comment") or ""),
        probability_of_playing=_as_float(row.get("probability_of_playing")),
    )


def _parse_news(row: Mapping[str, Any]) -> NewsItem:
    item_id = _as_int(row.get("id"))
    if item_id is None:
        raise DataAPIError("news row missing id")
    categories = row.get("categories")
    cats = tuple(str(c) for c in categories) if isinstance(categories, list) else ()
    return NewsItem(
        item_id=item_id,
        player_id=_as_int(row.get("player_id")),
        title=str(row.get("title") or ""),
        desc=str(row.get("desc") or ""),
        impact=str(row.get("impact") or ""),
        categories=cats,
        created=str(row.get("created") or ""),
    )


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)

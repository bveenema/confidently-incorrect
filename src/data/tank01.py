"""Tank01 (RapidAPI) NFL client: projections, injuries, news, odds.

Secondary projection source (D-20 / D-87). Provider fantasy-point totals
are dropped (D-48 / D-84). Stat keys map onto scoring-engine slugs.
Implied team totals are derived from betting lines, not returned raw.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from data.errors import DataAPIError, DataConfigError

API_HOST = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
API_BASE = f"https://{API_HOST}"
ATTRIBUTION = (
    "Secondary projections, injuries, news, and betting odds: Tank01 "
    "(https://www.tank01.com/) via RapidAPI."
)
USER_AGENT = "confidently-incorrect/0.1"
_LINUX_DEFAULT = Path("/srv/ci")
_CREDENTIALS_NAME = "tank01.json"
_PLACEHOLDER = "REPLACE_ME"
_TEMPLATE_HINT = (
    "Copy templates/tank01.json to $CI_STATE_DIR/tokens/tank01.json "
    "and replace api_key."
)
# Prefer a stable book when several are present on a game.
_PREFERRED_BOOKS = ("draftkings", "fanduel", "betmgm", "caesars")

# Nested Tank01 field → engine slug. Not league values — names only.
PASSING_MAP = {
    "passCompletions": "pass_cmp",
    "passAttempts": "pass_att",
    "passYds": "pass_yd",
    "passTD": "pass_td",
    "int": "pass_int",
}
RUSHING_MAP = {
    "carries": "rush_att",
    "rushYds": "rush_yd",
    "rushTD": "rush_td",
}
RECEIVING_MAP = {
    "receptions": "rec",
    "recYds": "rec_yd",
    "recTD": "rec_td",
}
KICKING_MAP = {
    # No distance bands (same gap as FantasyPros / A-13). Keep volume.
    "fgMade": "fg",
    "xpMade": "pat_made",
    "xpMissed": "pat_miss",
}
DST_MAP = {
    "sacks": "dst_sack",
    "interceptions": "dst_int",
    "fumbleRecoveries": "dst_fum_rec",
    "defTD": "dst_td",
    "safeties": "dst_safety",
    "blockKick": "dst_blk",
    "ptsAgainst": "dst_pts_allowed",
}


@dataclass(frozen=True)
class Tank01Credentials:
    api_key: str


@dataclass(frozen=True)
class PlayerProjection:
    player_id: str
    name: str
    position: str
    team: str
    stats: dict[str, float]


@dataclass(frozen=True)
class ProjectionSet:
    season: int | None
    week: str
    players: tuple[PlayerProjection, ...]
    defenses: tuple[PlayerProjection, ...]


@dataclass(frozen=True)
class PlayerIdentity:
    player_id: str
    yahoo_id: str | None
    name: str
    position: str
    team: str


@dataclass(frozen=True)
class Injury:
    player_id: str
    yahoo_id: str | None
    name: str
    position: str
    team: str
    designation: str
    description: str
    inj_date: str
    inj_return_date: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    player_ids: tuple[str, ...]
    image: str


@dataclass(frozen=True)
class ImpliedTeamTotal:
    game_id: str
    game_date: str
    home_team: str
    away_team: str
    book: str
    total: float
    home_spread: float
    home_implied: float
    away_implied: float


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


def load_credentials(root: Path | None = None) -> Tank01Credentials:
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
    return Tank01Credentials(api_key=key.strip())


def credentials_exist(root: Path | None = None) -> bool:
    try:
        load_credentials(root)
    except DataConfigError:
        return False
    return True


def map_player_stats(row: Mapping[str, Any]) -> dict[str, float]:
    """Flatten nested Tank01 projection blocks onto engine slugs.

    Drops `fantasyPointsDefault` and any unmapped field. `fgMissed` is
    folded into `fga` with `fgMade` so issue 8 can see attempt volume.
    """
    mapped: dict[str, float] = {}
    _merge_block(mapped, row.get("Passing"), PASSING_MAP)
    _merge_block(mapped, row.get("Rushing"), RUSHING_MAP)
    _merge_block(mapped, row.get("Receiving"), RECEIVING_MAP)
    kicking = row.get("Kicking")
    _merge_block(mapped, kicking, KICKING_MAP)
    if isinstance(kicking, Mapping):
        made = _as_float(kicking.get("fgMade"))
        missed = _as_float(kicking.get("fgMissed"))
        if made is not None or missed is not None:
            mapped["fga"] = (made or 0.0) + (missed or 0.0)
    for key, slug in (("fumblesLost", "fum_lost"), ("twoPointConversion", "two_pt")):
        number = _as_float(row.get(key))
        if number is not None:
            mapped[slug] = number
    return mapped


def map_defense_stats(row: Mapping[str, Any]) -> dict[str, float]:
    """Map a Tank01 team-defense projection. No return yards in the API."""
    mapped: dict[str, float] = {}
    for key, slug in DST_MAP.items():
        number = _as_float(row.get(key))
        if number is not None:
            mapped[slug] = number
    return mapped


def implied_totals_from_game(game: Mapping[str, Any]) -> ImpliedTeamTotal | None:
    """Derive home/away implied points from total and home spread."""
    book_name, book = _pick_book(game)
    if book is None or book_name is None:
        return None
    total = _as_float(book.get("totalOver"))
    if total is None:
        total = _as_float(book.get("totalUnder"))
    home_spread = _as_float(book.get("homeTeamSpread"))
    if total is None or home_spread is None:
        return None
    home_implied = (total - home_spread) / 2.0
    away_implied = (total + home_spread) / 2.0
    return ImpliedTeamTotal(
        game_id=str(game.get("gameID") or ""),
        game_date=str(game.get("gameDate") or ""),
        home_team=str(game.get("homeTeam") or ""),
        away_team=str(game.get("awayTeam") or ""),
        book=book_name,
        total=total,
        home_spread=home_spread,
        home_implied=home_implied,
        away_implied=away_implied,
    )


def _default_http() -> httpx.Client:
    return httpx.Client(
        timeout=60.0,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


class Tank01Client:
    """Load the RapidAPI key from the state volume and read Tank01 NFL."""

    def __init__(
        self,
        state_dir: Path,
        http: httpx.Client | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._http = http or _default_http()
        self._owns_http = http is None
        self._creds: Tank01Credentials | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Tank01Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def projections(self, *, week: int | str | None = None) -> ProjectionSet:
        """Weekly or season-long projections.

        `week` None / 0 / \"season\" → season-long (`body.week == \"season\"`).
        Positive int → that NFL week.
        """
        params: dict[str, str] = {}
        if week is None or week == 0 or week == "season":
            params["week"] = "season"
        else:
            params["week"] = str(week)
        payload = self._get("/getNFLProjections", params)
        body = _response_body(payload, "/getNFLProjections")
        if not isinstance(body, dict):
            raise DataAPIError("Tank01 getNFLProjections body must be an object")
        players = tuple(
            _parse_player_projection(pid, row)
            for pid, row in _object_map(body, "playerProjections").items()
        )
        defenses = tuple(
            _parse_defense_projection(tid, row)
            for tid, row in _object_map(body, "teamDefenseProjections").items()
        )
        return ProjectionSet(
            season=_as_int(body.get("season")),
            week=str(body.get("week") or params["week"]),
            players=players,
            defenses=defenses,
        )

    def player_list(self) -> tuple[PlayerIdentity, ...]:
        """Full getNFLPlayerList — identity + Yahoo id for the merge key."""
        body = self._player_list_body()
        out: list[PlayerIdentity] = []
        for row in body:
            parsed = _parse_identity(row)
            if parsed is not None:
                out.append(parsed)
        return tuple(out)

    def injuries(self) -> tuple[Injury, ...]:
        """Players with a non-empty injury designation from getNFLPlayerList."""
        out: list[Injury] = []
        for row in self._player_list_body():
            parsed = _parse_injury(row)
            if parsed is not None:
                out.append(parsed)
        return tuple(out)

    def _player_list_body(self) -> list[dict[str, Any]]:
        payload = self._get("/getNFLPlayerList", {})
        body = _response_body(payload, "/getNFLPlayerList")
        if not isinstance(body, list):
            raise DataAPIError("Tank01 getNFLPlayerList body must be a list")
        return [row for row in body if isinstance(row, dict)]

    def news(
        self,
        *,
        recent: bool = True,
        fantasy: bool = False,
        player_id: str | None = None,
    ) -> tuple[NewsItem, ...]:
        params: dict[str, str] = {}
        if player_id:
            params["playerID"] = player_id
        elif fantasy:
            params["fantasyNews"] = "true"
        elif recent:
            params["recentNews"] = "true"
        payload = self._get("/getNFLNews", params)
        body = _response_body(payload, "/getNFLNews")
        if not isinstance(body, list):
            raise DataAPIError("Tank01 getNFLNews body must be a list")
        return tuple(_parse_news(row) for row in body if isinstance(row, dict))

    def betting_odds(self, game_date: str) -> dict[str, dict[str, Any]]:
        """Raw odds map keyed by gameID for `YYYYMMDD`."""
        payload = self._get("/getNFLBettingOdds", {"gameDate": game_date})
        body = _response_body(payload, "/getNFLBettingOdds")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise DataAPIError("Tank01 getNFLBettingOdds body must be an object")
        games: dict[str, dict[str, Any]] = {}
        for game_id, row in body.items():
            if isinstance(row, dict):
                games[str(game_id)] = row
        return games

    def implied_team_totals(self, game_date: str) -> tuple[ImpliedTeamTotal, ...]:
        games = self.betting_odds(game_date)
        out: list[ImpliedTeamTotal] = []
        for game in games.values():
            derived = implied_totals_from_game(game)
            if derived is not None:
                out.append(derived)
        return tuple(out)

    def smoke(self, *, odds_date: str) -> dict[str, Any]:
        """Hit season + week-1 projections, injuries, news, and one odds day."""
        season = self.projections(week="season")
        week1 = self.projections(week=1)
        injuries = self.injuries()
        news = self.news(recent=True)
        totals = self.implied_team_totals(odds_date)
        if not season.players or not week1.players:
            raise DataAPIError(
                "Tank01 smoke got an empty projection set "
                f"(season={len(season.players)} week1={len(week1.players)})."
            )
        sample = next(
            (p for p in week1.players if p.position == "QB" and "pass_yd" in p.stats),
            None,
        )
        if sample is None or "pass_cmp" not in sample.stats:
            raise DataAPIError(
                "Tank01 week-1 projections lack skill-position stat lines "
                "(expected Passing.passCompletions / passYds)."
            )
        return {
            "attribution": ATTRIBUTION,
            "season_count": len(season.players),
            "season_dst_count": len(season.defenses),
            "week1_count": len(week1.players),
            "week1_dst_count": len(week1.defenses),
            "sample_qb_pass_yd": sample.stats.get("pass_yd"),
            "injuries_count": len(injuries),
            "news_count": len(news),
            "implied_totals_count": len(totals),
            "odds_date": odds_date,
        }

    def _credentials(self) -> Tank01Credentials:
        if self._creds is None:
            self._creds = load_credentials(self._state_dir)
        return self._creds

    def _get(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        response = self._http.get(
            f"{API_BASE}{path}",
            params=dict(params),
            headers={
                "x-rapidapi-key": self._credentials().api_key,
                "x-rapidapi-host": API_HOST,
            },
        )
        if response.status_code != 200:
            raise DataAPIError(
                f"Tank01 GET {path} failed: status={response.status_code}"
            )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DataAPIError(f"Tank01 GET {path} returned non-JSON") from exc
        if not isinstance(payload, dict):
            raise DataAPIError(f"Tank01 GET {path} returned a non-object JSON body")
        return payload


def _response_body(payload: Mapping[str, Any], path: str) -> Any:
    if "body" not in payload:
        return payload
    status = payload.get("statusCode")
    if status is not None and _as_int(status) not in (None, 200):
        raise DataAPIError(f"Tank01 GET {path} failed: statusCode={status}")
    return payload.get("body")


def _object_map(body: Mapping[str, Any], key: str) -> dict[str, dict[str, Any]]:
    raw = body.get(key)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DataAPIError(f"Tank01 field {key!r} must be an object")
    out: dict[str, dict[str, Any]] = {}
    for item_id, row in raw.items():
        if isinstance(row, dict):
            out[str(item_id)] = row
    return out


def _parse_player_projection(
    player_id: str, row: Mapping[str, Any]
) -> PlayerProjection:
    pid = str(row.get("playerID") or player_id)
    pos = str(row.get("pos") or "")
    if pos == "PK":
        pos = "K"
    return PlayerProjection(
        player_id=pid,
        name=str(row.get("longName") or ""),
        position=pos,
        team=str(row.get("team") or ""),
        stats=map_player_stats(row),
    )


def _parse_defense_projection(team_id: str, row: Mapping[str, Any]) -> PlayerProjection:
    tid = str(row.get("teamID") or team_id)
    abv = str(row.get("teamAbv") or "")
    return PlayerProjection(
        player_id=tid,
        name=f"{abv} DST" if abv else f"DST {tid}",
        position="DST",
        team=abv,
        stats=map_defense_stats(row),
    )


def _parse_identity(row: Mapping[str, Any]) -> PlayerIdentity | None:
    player_id = str(row.get("playerID") or "").strip()
    if not player_id:
        return None
    yahoo = row.get("yahooPlayerID")
    pos = str(row.get("pos") or "")
    if pos == "PK":
        pos = "K"
    return PlayerIdentity(
        player_id=player_id,
        yahoo_id=str(yahoo) if yahoo not in (None, "") else None,
        name=str(row.get("longName") or ""),
        position=pos,
        team=str(row.get("team") or ""),
    )


def _parse_injury(row: Mapping[str, Any]) -> Injury | None:
    inj = row.get("injury")
    if not isinstance(inj, Mapping):
        return None
    designation = str(inj.get("designation") or "").strip()
    description = str(inj.get("description") or "").strip()
    if not designation and not description:
        return None
    player_id = str(row.get("playerID") or "").strip()
    if not player_id:
        return None
    yahoo = row.get("yahooPlayerID")
    pos = str(row.get("pos") or "")
    if pos == "PK":
        pos = "K"
    return Injury(
        player_id=player_id,
        yahoo_id=str(yahoo) if yahoo not in (None, "") else None,
        name=str(row.get("longName") or ""),
        position=pos,
        team=str(row.get("team") or ""),
        designation=designation,
        description=description,
        inj_date=str(inj.get("injDate") or ""),
        inj_return_date=str(inj.get("injReturnDate") or ""),
    )


def _parse_news(row: Mapping[str, Any]) -> NewsItem:
    player_ids: list[str] = []
    raw_ids = row.get("playerIDs")
    if isinstance(raw_ids, list):
        player_ids.extend(str(x) for x in raw_ids if x not in (None, ""))
    single = row.get("playerID")
    if single not in (None, ""):
        player_ids.append(str(single))
    return NewsItem(
        title=str(row.get("title") or ""),
        link=str(row.get("link") or ""),
        player_ids=tuple(dict.fromkeys(player_ids)),
        image=str(row.get("image") or ""),
    )


def _pick_book(
    game: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any] | None]:
    books: dict[str, dict[str, Any]] = {}
    for key, value in game.items():
        if not isinstance(value, dict):
            continue
        if "homeTeamSpread" in value or "totalOver" in value:
            books[str(key)] = value
    if not books:
        return None, None
    for name in _PREFERRED_BOOKS:
        if name in books:
            return name, books[name]
    name = next(iter(books))
    return name, books[name]


def _merge_block(
    mapped: dict[str, float],
    block: Any,
    field_map: Mapping[str, str],
) -> None:
    if not isinstance(block, Mapping):
        return
    for key, slug in field_map.items():
        number = _as_float(block.get(key))
        if number is not None:
            mapped[slug] = number


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

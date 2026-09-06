"""CLI: serve the local draft-board page."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from data.errors import DataError
from data.league_settings import load_league_settings, state_dir
from draft.errors import DraftConfigError, DraftError
from draft.pool_load import load_draft_pool
from draft.rehearsal import rehearsal_root
from draft.server import DraftApp, require_snake, start_server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m draft")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser(
        "serve",
        help="local page for pick entry, next pick, and available pool",
    )
    serve.add_argument("--host", default="127.0.0.1", help="bind address")
    serve.add_argument("--port", type=int, default=8765, help="bind port")
    serve.add_argument(
        "--season",
        type=int,
        default=0,
        help="NFL season year (default: current year in America/New_York)",
    )
    serve.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild the player-pool snapshot from live APIs",
    )
    serve.add_argument(
        "--state-dir",
        type=Path,
        help="rehearsal root (rejected if it is the live runtime root)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "serve":
        return _serve(args.host, args.port, args.season, args.refresh, args.state_dir)
    print(f"error: unknown command {args.command!r}", file=sys.stderr)
    return 2


def _serve(
    host: str,
    port: int,
    season: int,
    refresh: bool,
    override: Path | None,
) -> int:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            "error: draft page binds localhost only "
            f"(got {host!r}). Issue 9 is a workstation tool.",
            file=sys.stderr,
        )
        return 2
    rehearsal = override is not None
    try:
        if rehearsal:
            if override is None:
                raise DraftConfigError("rehearsal requested without --state-dir")
            root = rehearsal_root(override)
        else:
            root = state_dir()
        settings = load_league_settings(root)
        require_snake(settings)
        print(
            f"loading player pool for {settings.team_count} teams / "
            f"{settings.draft.rounds} rounds...",
            flush=True,
        )
        pool = load_draft_pool(root, settings, season=season, refresh=refresh)
    except DraftConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if rehearsal else 1
    except (DraftError, DataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: unexpected failure starting draft board: {exc}", file=sys.stderr)
        return 1
    year = season or datetime.now(ZoneInfo("America/New_York")).year
    app = DraftApp(root, pool, rehearsal=rehearsal, season_id=str(year))
    httpd = start_server(app, host=host, port=port)
    bound = httpd.server_address[1]
    mode = "REHEARSAL " if rehearsal else ""
    print(
        f"ok: {mode}draft board at http://{host}:{bound}/ "
        f"({len(pool.players)} players, "
        f"{settings.team_count} teams, {settings.draft.rounds} rounds)",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("ok: stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

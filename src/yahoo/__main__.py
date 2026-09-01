"""CLI: one-time oob authorize, then an unattended smoke read."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from yahoo.client import YahooClient
from yahoo.errors import YahooError
from yahoo.oauth import authorize_url
from yahoo.paths import state_dir
from yahoo.tokens import load_app_credentials


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m yahoo")
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("authorize", help="one-time browser OAuth (oob)")
    auth.add_argument(
        "--code",
        help="verification code from Yahoo (omit to print the URL and prompt)",
    )

    sub.add_parser("smoke", help="read own team, league settings, and roster")

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        root = state_dir()
        if args.command == "authorize":
            return _authorize(root, args.code)
        return _smoke(root)
    except YahooError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _authorize(root: Path, code: str | None) -> int:
    creds = load_app_credentials(root)
    url = authorize_url(creds.client_id)
    if not code:
        print(url)
        print("Open that URL, authorize the app, then paste the verification code.")
        try:
            code = input("code: ").strip()
        except EOFError:
            print("error: no code provided", file=sys.stderr)
            return 2
    if not code:
        print("error: empty code", file=sys.stderr)
        return 2
    with YahooClient(root) as client:
        path = client.authorize(code)
    print(f"token written to {path}")
    return 0


def _smoke(root: Path) -> int:
    with YahooClient(root) as client:
        result = client.smoke()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

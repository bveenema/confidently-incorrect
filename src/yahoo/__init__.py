"""Yahoo Fantasy API client."""

from yahoo.client import YahooClient
from yahoo.errors import YahooAPIError, YahooAuthError, YahooConfigError, YahooError

__all__ = [
    "YahooAPIError",
    "YahooAuthError",
    "YahooClient",
    "YahooConfigError",
    "YahooError",
    "healthcheck",
]


def healthcheck() -> str:
    return "ok"

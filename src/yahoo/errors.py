"""Yahoo client errors. Auth failures are never swallowed (O-9)."""


class YahooError(Exception):
    """Base for every Yahoo client failure."""


class YahooConfigError(YahooError):
    """Missing or invalid local credentials / token files."""


class YahooAuthError(YahooError):
    """401 or invalid_grant. Reauthorization needs a browser."""


class YahooAPIError(YahooError):
    """Non-auth Yahoo failure, including access-program 403s."""

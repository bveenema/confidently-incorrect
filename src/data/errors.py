"""Errors for the data package. Write-path failures must not be swallowed."""


class DataError(Exception):
    """Base for every data-package failure."""


class LeagueSettingsError(DataError):
    """Missing or invalid $CI_STATE_DIR/league-settings.json."""


class DataConfigError(DataError):
    """Missing or invalid local credentials / state-dir files."""


class DataAPIError(DataError):
    """Non-config failure talking to a data provider."""

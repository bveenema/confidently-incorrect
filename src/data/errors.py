"""Errors for the data package. Write-path failures must not be swallowed."""


class DataError(Exception):
    """Base for every data-package failure."""


class LeagueSettingsError(DataError):
    """Missing or invalid $CI_STATE_DIR/league-settings.json."""

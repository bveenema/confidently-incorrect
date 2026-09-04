"""Ledger errors. Write-path failures must not be swallowed."""


class DbError(Exception):
    """Base for every kb.db failure."""


class DbConfigError(DbError):
    """Missing state dir, missing schema file, or migrate/connect failure."""

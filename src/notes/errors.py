"""Errors for the notes vault. Write-path failures must not be swallowed."""


class NotesError(Exception):
    """Base for every notes-package failure."""


class NotesStateError(NotesError):
    """Missing, invalid, or conflicting notes file under the state root."""

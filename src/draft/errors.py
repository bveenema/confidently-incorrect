"""Errors for the draft board. Write-path failures must not be swallowed."""


class DraftError(Exception):
    """Base for every draft-package failure."""


class DraftConfigError(DraftError):
    """Missing or invalid league settings / pool snapshot for draft night."""


class DraftStateError(DraftError):
    """Missing, invalid, or conflicting $CI_STATE_DIR/draft-board.json."""

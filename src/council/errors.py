"""Council errors. Write-path failures must not be swallowed."""


class CouncilError(Exception):
    """Base for every council failure."""


class CouncilConfigError(CouncilError):
    """Missing or invalid OpenRouter credentials / state dir."""


class CouncilAPIError(CouncilError):
    """OpenRouter HTTP or payload failure."""


class CouncilValidationError(CouncilError):
    """Malformed brief or GM decision. Not retried."""


class CouncilRunError(CouncilError):
    """A council run started and then failed (usually a missing GM)."""

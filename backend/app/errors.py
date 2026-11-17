class DomainError(Exception):
    """Business rule violation. The API layer maps subclasses to HTTP codes."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404


class ForbiddenError(DomainError):
    """Not one of our campaigns: we never read or write other candidates' campaigns."""

    status_code = 403


class ConflictError(DomainError):
    """Action does not fit the current state (already removed, nothing to push...)."""

    status_code = 409


class InvalidError(DomainError):
    """Input breaks a rule (pins over 100, share out of range, bad geo...)."""

    status_code = 422

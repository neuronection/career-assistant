class DomainError(Exception):
    """Base class for user-facing domain errors."""


class AINotConfiguredError(DomainError):
    """AI features are unavailable in this environment (e.g. mock in production)."""


class NotFoundError(DomainError):
    """Requested entity does not exist."""


class PermissionDeniedError(DomainError):
    """Caller is not allowed to perform this action."""


class ValidationError(DomainError):
    """Payload failed domain validation."""


class ConflictError(DomainError):
    """Target changed since it was proposed — review before applying."""


class AccountLockedError(DomainError):
    """Too many failed logins; the account is temporarily locked."""

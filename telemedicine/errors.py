"""Exception types for the telemedicine application layer.

The distinction matters to callers: an :class:`AuthenticationError` means "who
are you, and is that right", an :class:`AuthorizationError` means "I know who
you are, but you may not do that". The audit log treats them differently, and
so should the API layer that ENG-006 will build.
"""


class TelemedicineError(Exception):
    """Base class for every error raised by the application layer."""


class ValidationError(TelemedicineError):
    """Input did not satisfy a documented rule (for example, a weak password)."""


class AuthenticationError(TelemedicineError):
    """Credentials are missing, wrong, expired, or the account is unusable."""


class AuthorizationError(TelemedicineError):
    """The caller is authenticated but not allowed to perform the action.

    ``resource_type``, ``resource_id`` and ``action`` are attached so the audit
    layer can record exactly what was refused.
    """

    def __init__(self, message, *, resource_type=None, resource_id=None, action=None):
        super().__init__(message)
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.action = action


class AuditError(TelemedicineError):
    """The audit log refused a write or failed its integrity check."""

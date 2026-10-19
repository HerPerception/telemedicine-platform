"""Core domain types for the security layer."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class Role(str, enum.Enum):
    """The two roles the MVP supports.

    The README describes a single-clinician practice with patients, so exactly
    two roles exist. A third (practice administrator) would be needed before
    the practice takes on staff.
    """

    PATIENT = "patient"
    PRACTITIONER = "practitioner"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


@dataclass(frozen=True)
class UserAccount:
    """A login account.

    ``record_id`` links the account to a row of the clinical model: the
    ``patient.id`` for a patient account, the ``practitioner.id`` for a
    practitioner account. In the database this is the ``account_ref`` column
    that ENG-001 added to ``patient`` and ``practitioner``; it is deliberately
    an opaque reference rather than a foreign key so that the two features do
    not depend on each other's table layout.
    """

    user_id: str
    email: str
    role: Role
    password_hash: str
    record_id: Optional[str] = None
    disabled: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.email:
            raise ValueError("email is required")
        if not isinstance(self.role, Role):
            raise TypeError("role must be a Role")
        if self.role in (Role.PATIENT, Role.PRACTITIONER) and not self.record_id:
            raise ValueError("record_id is required for patient and practitioner accounts")

    @property
    def is_active(self) -> bool:
        return not self.disabled


@dataclass(frozen=True)
class Session:
    """An authentication session.

    The raw token is returned to the caller exactly once, at creation time.
    Only :attr:`token_hash` is stored, so a leaked database cannot be used to
    impersonate a user. ``session_id`` is what the audit log refers to.
    """

    session_id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

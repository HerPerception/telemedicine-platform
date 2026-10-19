"""Telemedicine MVP application layer.

This package holds the application code that sits on top of the clinical data
model defined in ``db/schema.sql`` (feature ENG-001). Feature ENG-002 adds the
security layer:

* :mod:`telemedicine.auth` — registration, password authentication and
  session management for both roles (patient and practitioner).
* :mod:`telemedicine.authorization` — role-scoped access decisions over the
  clinical resources.
* :mod:`telemedicine.audit` — the append-only, tamper-evident audit log.
* :mod:`telemedicine.records` — the service layer that ties the three
  together: it authorizes every access to a record or a prescription and
  writes the audit entry for it.

Only the Python 3.12 standard library is used. Persistence is not implemented
yet: the PostgreSQL schema for accounts, sessions and the audit log is in
``db/auth_schema.sql`` and the repositories here are in-memory.
"""

from telemedicine.audit import AuditEntry, AuditLog
from telemedicine.auth import AuthService, Session
from telemedicine.authorization import (
    AccessScope,
    Action,
    Authorizer,
    Decision,
    ResourceType,
)
from telemedicine.errors import (
    AuthenticationError,
    AuthorizationError,
    AuditError,
    TelemedicineError,
    ValidationError,
)
from telemedicine.models import Role, UserAccount
from telemedicine.records import Prescription, RecordsService
from telemedicine.security import hash_password, verify_password

__all__ = [
    "AccessScope",
    "Action",
    "AuditEntry",
    "AuditError",
    "AuditLog",
    "AuthService",
    "AuthenticationError",
    "AuthorizationError",
    "Authorizer",
    "Decision",
    "Prescription",
    "RecordsService",
    "ResourceType",
    "Role",
    "Session",
    "TelemedicineError",
    "UserAccount",
    "ValidationError",
    "hash_password",
    "verify_password",
]

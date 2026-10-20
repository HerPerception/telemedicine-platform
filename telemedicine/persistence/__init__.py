"""Persistence: the database, the durable audit log and the shared lockout.

* :mod:`telemedicine.persistence.database` — the connection, the schema files
  and the transactions.
* :mod:`telemedicine.persistence.audit_store` — the audit log that survives a
  restart, which is what makes the hash chain worth anything.
* :mod:`telemedicine.persistence.lockout` — the failed-attempt counter that
  several instances share, which is what makes a lockout worth anything.
"""

from telemedicine.persistence.audit_store import PostgresAuditLog
from telemedicine.persistence.database import Database, SchemaError, SchemaReport
from telemedicine.persistence.lockout import (
    InMemoryLockoutStore,
    LockoutStore,
    PostgresLockoutStore,
)

__all__ = [
    "Database",
    "InMemoryLockoutStore",
    "LockoutStore",
    "PostgresAuditLog",
    "PostgresLockoutStore",
    "SchemaError",
    "SchemaReport",
]

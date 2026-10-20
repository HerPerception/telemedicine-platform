"""The audit log that survives a restart.

The hash chain of ENG-002 is only worth something if the entries are still
there tomorrow. This is the same log, in the ``audit_log`` table of
``db/auth_schema.sql``.

The one hard part is the chain itself: every entry hashes the entry before
it, so two writers that read the same chain head would fork it. The append
therefore happens inside a transaction that holds a PostgreSQL advisory lock,
and the chain head is read in that same transaction. The lock is released
when the transaction ends, whether it committed or not.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from telemedicine.audit import AuditEntry, GENESIS_HASH, hash_payload
from telemedicine.persistence.database import AUDIT_LOCK_KEY, Database

_COLUMNS = (
    "sequence", "occurred_at", "actor_user_id", "actor_role", "action",
    "resource_type", "resource_id", "outcome", "detail", "previous_hash",
    "entry_hash",
)


def _row_to_entry(row) -> AuditEntry:
    """Turn a row into an entry, with the same types the hash was built from.

    The driver hands back a ``uuid`` and a ``datetime``; the hash was
    computed over the strings. Reading an entry without normalising them
    would make the chain look broken.
    """
    values = list(row)
    if values[2] is not None:
        values[2] = str(values[2])
    if isinstance(values[1], datetime):
        values[1] = values[1].isoformat().replace("+00:00", "Z")
    return AuditEntry(*values)


class PostgresAuditLog:
    """An audit log in the database.

    It presents the same ``append`` interface as the in-memory log of
    ENG-002, so a service can be given either.
    """

    def __init__(self, database: Database):
        self.database = database

    # -- writing ----------------------------------------------------------

    def append(self, *, actor_user_id: str, actor_role: str, action: str,
               resource_type: str, resource_id: str, outcome: str,
               detail: str = "") -> AuditEntry:
        """Append an entry, and return it.

        The chain head is read and the row written in one transaction, under
        an advisory lock, so that the chain cannot fork.
        """
        with self.database.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK_KEY,))
            cursor.execute(
                "SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1")
            row = cursor.fetchone()
            previous_hash = row[0] if row else GENESIS_HASH

            cursor.execute("SELECT nextval('audit_log_sequence_seq')")
            sequence = int(cursor.fetchone()[0])

            payload = {
                "sequence": sequence,
                "occurred_at": _now(),
                "actor_user_id": actor_user_id,
                "actor_role": actor_role,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "detail": detail,
                "previous_hash": previous_hash,
            }
            entry_hash = hash_payload(payload)
            cursor.execute(
                "INSERT INTO audit_log (sequence, occurred_at, actor_user_id, actor_role,"
                " action, resource_type, resource_id, outcome, detail, previous_hash,"
                " entry_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (sequence, payload["occurred_at"], actor_user_id, actor_role, action,
                 resource_type, resource_id, outcome, detail, previous_hash, entry_hash))
            return AuditEntry(entry_hash=entry_hash, **payload)

    # -- reading ----------------------------------------------------------

    def load(self) -> List[AuditEntry]:
        """Every entry, oldest first."""
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM audit_log ORDER BY sequence")
                return [_row_to_entry(row) for row in cursor.fetchall()]

    @property
    def entries(self) -> List[AuditEntry]:
        """The entries, oldest first. A snapshot, like the in-memory log's."""
        return self.load()

    def __len__(self) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM audit_log")
                return int(cursor.fetchone()[0])

    def __iter__(self):
        return iter(self.load())

    # -- integrity --------------------------------------------------------

    def head_hash(self) -> Optional[str]:
        """The hash of the last entry, or None when the log is empty."""
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT entry_hash FROM audit_log ORDER BY sequence DESC LIMIT 1")
                row = cursor.fetchone()
                return row[0] if row else None

    def verify_chain(self) -> bool:
        """Whether every entry hashes correctly and links to its predecessor."""
        return self.find_chain_break() is None

    def find_chain_break(self) -> Optional[int]:
        """The sequence of the first broken entry, or None."""
        previous_hash = GENESIS_HASH
        expected_sequence = 1
        for entry in self.load():
            if entry.sequence != expected_sequence:
                return entry.sequence
            if entry.previous_hash != previous_hash:
                return entry.sequence
            if entry.compute_hash() != entry.entry_hash:
                return entry.sequence
            previous_hash = entry.entry_hash
            expected_sequence += 1
        return None

    def entries_for_resource(self, resource_type: str, resource_id: str) -> List[AuditEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM audit_log"
                    " WHERE resource_type = %s AND resource_id = %s ORDER BY sequence",
                    (resource_type, resource_id))
                return [_row_to_entry(row) for row in cursor.fetchall()]

    def entries_for_actor(self, actor_user_id: str) -> List[AuditEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM audit_log"
                    " WHERE actor_user_id = %s ORDER BY sequence", (actor_user_id,))
                return [_row_to_entry(row) for row in cursor.fetchall()]

    def entries_for_outcome(self, outcome: str) -> List[AuditEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM audit_log"
                    " WHERE outcome = %s ORDER BY sequence", (outcome,))
                return [_row_to_entry(row) for row in cursor.fetchall()]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

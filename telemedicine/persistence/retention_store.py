"""The trash and the deletion audit, in the database.

The two tables of ``db/retention_schema.sql``:

* ``deleted_record`` — the trash. A record that has been soft-deleted is kept
  here, whole, until its grace period has passed.
* ``deletion_audit`` — every removal, and why. The table is append-only: the
  schema refuses a change to a row and refuses its removal, because a record
  of what was deleted that could be edited afterwards would not be evidence
  of anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from telemedicine.persistence.database import Database
from telemedicine.retention import DeletionAuditEntry, TrashedRecord


class PostgresRetentionStore:
    """The trash and the deletion audit, in the ``deleted_record`` and
    ``deletion_audit`` tables."""

    def __init__(self, database: Database):
        self.database = database

    # -- the trash ---------------------------------------------------------

    def trash(self) -> List[TrashedRecord]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, record_type, record_id, patient_id, payload,"
                    " deleted_at, purge_after FROM deleted_record"
                    " ORDER BY deleted_at, id")
                return [_to_trashed(row) for row in cursor.fetchall()]

    def add_trash(self, record: TrashedRecord) -> TrashedRecord:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO deleted_record (id, record_type, record_id, patient_id,"
                " payload, deleted_at, purge_after)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (record.trash_id, record.record_type, record.record_id,
                 record.patient_id, record.payload, record.deleted_at,
                 record.purge_after))
        return record

    def remove_trash(self, trash_id: str) -> None:
        with self.database.transaction() as cursor:
            cursor.execute("DELETE FROM deleted_record WHERE id = %s", (trash_id,))

    # -- the live rows -----------------------------------------------------

    def mark_deleted(self, record_type: str, record_id: str,
                     deleted_at: datetime) -> int:
        """The clinical store does this: the tables are its own."""
        from telemedicine.persistence.clinical_store import PostgresClinicalRepository
        return PostgresClinicalRepository(self.database).mark_deleted(
            record_type, record_id, deleted_at)

    def purge_deleted(self, record_type: str, record_id: str) -> int:
        from telemedicine.persistence.clinical_store import PostgresClinicalRepository
        return PostgresClinicalRepository(self.database).purge_deleted(
            record_type, record_id)

    # -- the audit ---------------------------------------------------------

    def record_deletion(self, entry: DeletionAuditEntry) -> DeletionAuditEntry:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO deletion_audit (id, record_type, record_id, patient_id,"
                " stage, occurred_at, reason, policy_source)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (entry.entry_id, entry.record_type, entry.record_id,
                 entry.patient_id, entry.stage, entry.occurred_at, entry.reason,
                 entry.policy_source))
        return entry

    def deletion_audit(self) -> List[DeletionAuditEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, record_type, record_id, patient_id, stage, occurred_at,"
                    " reason, policy_source FROM deletion_audit ORDER BY occurred_at, id")
                return [_to_audit(row) for row in cursor.fetchall()]


def _to_trashed(row) -> TrashedRecord:
    payload = row[4]
    if not isinstance(payload, str):
        import json
        payload = json.dumps(payload)
    return TrashedRecord(
        trash_id=str(row[0]),
        record_type=row[1],
        record_id=row[2],
        patient_id=str(row[3]) if row[3] else None,
        payload=payload,
        deleted_at=row[5],
        purge_after=row[6],
    )


def _to_audit(row) -> DeletionAuditEntry:
    return DeletionAuditEntry(
        entry_id=str(row[0]),
        record_type=row[1],
        record_id=row[2],
        patient_id=str(row[3]) if row[3] else None,
        stage=row[4],
        occurred_at=row[5],
        reason=row[6],
        policy_source=row[7] or "",
    )

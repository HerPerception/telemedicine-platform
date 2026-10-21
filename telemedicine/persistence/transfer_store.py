"""The log of transfers out of Nigeria, in the database.

Section 41(2) of the Nigeria Data Protection Act 2023 requires the basis for
a transfer to be recorded. This is where it is recorded: the ``transfer_logs``
table of ``db/transfer_schema.sql``.

The table is append-only — the schema refuses a change to a row and refuses
its removal — because a transfer that could be edited afterwards would not be
a record of the transfer.
"""

from __future__ import annotations

from typing import List, Optional

from telemedicine.persistence.database import Database
from telemedicine.transfer import TransferLog, TransferLogEntry


class PostgresTransferLog(TransferLog):
    """The transfers, in the ``transfer_logs`` table."""

    def __init__(self, database: Database):
        self.database = database

    def record(self, entry: TransferLogEntry) -> TransferLogEntry:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO transfer_logs (occurred_at, service, destination,"
                " destination_country, recipient, data_categories, lawful_basis,"
                " justification, user_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (entry.occurred_at, entry.service, entry.destination,
                 entry.destination_country, entry.recipient,
                 list(entry.data_categories), entry.lawful_basis,
                 entry.justification, entry.user_id))
        return entry

    def entries(self) -> List[TransferLogEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT occurred_at, service, destination, destination_country,"
                    " recipient, data_categories, lawful_basis, justification, user_id"
                    " FROM transfer_logs ORDER BY occurred_at, id")
                return [_to_entry(row) for row in cursor.fetchall()]

    def for_destination(self, destination: str) -> List[TransferLogEntry]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT occurred_at, service, destination, destination_country,"
                    " recipient, data_categories, lawful_basis, justification, user_id"
                    " FROM transfer_logs WHERE destination = %s"
                    " ORDER BY occurred_at, id", (destination,))
                return [_to_entry(row) for row in cursor.fetchall()]


def _to_entry(row) -> TransferLogEntry:
    categories = row[5]
    if isinstance(categories, str):
        categories = [item for item in categories.strip("{}").split(",") if item]
    return TransferLogEntry(
        occurred_at=row[0],
        service=row[1] or "",
        destination=row[2],
        destination_country=row[3],
        recipient=row[4] or "",
        data_categories=list(categories or []),
        lawful_basis=row[6],
        justification=row[7] or "",
        user_id=str(row[8]) if row[8] else None,
    )

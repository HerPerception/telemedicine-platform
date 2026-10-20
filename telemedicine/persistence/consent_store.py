"""The consent events, in the database.

The table is append-only, so the store only ever inserts.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from telemedicine.consent import ConsentEvent, ConsentStore
from telemedicine.persistence.database import Database


class PostgresConsentStore(ConsentStore):
    """The consent events, in the ``consent_event`` table."""

    def __init__(self, database: Database):
        self.database = database

    def append(self, event: ConsentEvent) -> ConsentEvent:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO consent_event (id, user_id, kind, purpose, notice_version,"
                " method, evidence, occurred_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (event.event_id, event.user_id, event.kind, event.purpose,
                 event.notice_version, event.method, event.evidence, event.occurred_at))
        return event

    def events_for(self, user_id: str) -> List[ConsentEvent]:
        return self._query("SELECT id, user_id, kind, purpose, notice_version, occurred_at,"
                           " method, evidence FROM consent_event"
                           " WHERE user_id = %s ORDER BY occurred_at", (user_id,))

    def events_for_purpose(self, user_id: str, purpose: str) -> List[ConsentEvent]:
        return self._query("SELECT id, user_id, kind, purpose, notice_version, occurred_at,"
                           " method, evidence FROM consent_event"
                           " WHERE user_id = %s AND purpose = %s ORDER BY occurred_at",
                           (user_id, purpose))

    def _query(self, statement: str, parameters) -> List[ConsentEvent]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                return [_to_event(row) for row in cursor.fetchall()]


def _to_event(row) -> ConsentEvent:
    return ConsentEvent(
        event_id=str(row[0]),
        user_id=str(row[1]),
        kind=row[2],
        purpose=row[3],
        notice_version=row[4] or "",
        occurred_at=row[5],
        method=row[6] or "web",
        evidence=row[7],
    )

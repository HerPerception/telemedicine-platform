"""The queued messages, in the database.

The outbox is a table rather than a queue in memory, because a confirmation
that was queued has to survive the process that queued it: a booking that
tells nobody about it is a booking that half happened.

The delivery process claims a message with ``FOR UPDATE SKIP LOCKED``, so
that two of them can run at once without sending the same message twice.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from telemedicine.notifications import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_SENT,
    Notification,
)
from telemedicine.persistence.database import Database

_COLUMNS = (
    "id", "kind", "recipient_user_id", "channel", "subject", "body", "status",
    "attempts", "last_error", "created_at", "sent_at",
)


class PostgresNotificationStore:
    """The queued messages, in the ``notification_outbox`` table."""

    def __init__(self, database: Database):
        self.database = database

    def enqueue(self, notification: Notification) -> Notification:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO notification_outbox (id, kind, recipient_user_id, channel, subject,"
                " body, status, attempts, last_error, created_at, sent_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (notification.notification_id, notification.kind,
                 notification.recipient_user_id, notification.channel, notification.subject,
                 notification.body, notification.status, notification.attempts,
                 notification.last_error, notification.created_at, notification.sent_at))
        return notification

    def pending(self, limit: int = 100) -> List[Notification]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM notification_outbox"
                    " WHERE status = 'queued' ORDER BY created_at LIMIT %s", (limit,))
                return [_to_notification(row) for row in cursor.fetchall()]

    def mark_sent(self, notification_id: str, when: datetime) -> None:
        with self.database.transaction() as cursor:
            cursor.execute(
                "UPDATE notification_outbox SET status = 'sent', sent_at = %s,"
                " attempts = attempts + 1, last_error = NULL WHERE id = %s",
                (when, notification_id))

    def mark_failed(self, notification_id: str, error: str, when: datetime) -> None:
        from telemedicine.notifications import MAX_ATTEMPTS
        with self.database.transaction() as cursor:
            cursor.execute(
                "UPDATE notification_outbox SET attempts = attempts + 1, last_error = %s,"
                " status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'queued' END"
                " WHERE id = %s",
                (error, MAX_ATTEMPTS, notification_id))

    def list_for_recipient(self, recipient_user_id: str) -> List[Notification]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM notification_outbox"
                    " WHERE recipient_user_id = %s ORDER BY created_at",
                    (recipient_user_id,))
                return [_to_notification(row) for row in cursor.fetchall()]

    def get(self, notification_id: str) -> Optional[Notification]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT " + ", ".join(_COLUMNS) + " FROM notification_outbox WHERE id = %s",
                    (notification_id,))
                row = cursor.fetchone()
        return _to_notification(row) if row else None

    def __len__(self) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM notification_outbox")
                return int(cursor.fetchone()[0])


def _to_notification(row) -> Notification:
    return Notification(
        notification_id=str(row[0]),
        kind=row[1],
        recipient_user_id=str(row[2]),
        subject=row[4],
        body=row[5],
        created_at=row[9],
        channel=row[3],
        status=row[6],
        attempts=row[7],
        last_error=row[8],
        sent_at=row[10],
    )

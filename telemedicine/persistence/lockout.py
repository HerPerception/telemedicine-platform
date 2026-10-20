"""The lockout: a counter that several instances share.

A login that fails has to be counted somewhere that every instance can see.
A counter in the memory of one process is no counter at all the moment the
application runs in two places, and a password-guessing attack is exactly
the case where an attacker will reach both.

The store behind the counter is a seam, and there are two implementations:
an in-memory one for a single process and for the tests, and one that uses
the ``auth_lockout`` table of ``db/security_schema.sql``.

The policy itself lives in :mod:`telemedicine.auth`, not here: this module
counts and stores, the service decides what to do with the count.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from telemedicine.persistence.database import Database


class LockoutStore:
    """What a lockout store has to be able to do."""

    def record_failure(self, key: str, now: datetime) -> int:
        """Count a failure and return the number of consecutive failures."""
        raise NotImplementedError

    def record_success(self, key: str) -> None:
        """Clear the counter of a key."""
        raise NotImplementedError

    def locked_until(self, key: str) -> Optional[datetime]:
        """When the lock on a key ends, or None when it is not locked."""
        raise NotImplementedError

    def set_locked_until(self, key: str, until: datetime) -> None:
        """Lock a key until a moment in time."""
        raise NotImplementedError

    def is_locked(self, key: str, now: datetime) -> bool:
        """Whether a key is locked at a given moment."""
        until = self.locked_until(key)
        return until is not None and now < until

    def attempts(self, key: str) -> int:
        """The number of consecutive failures counted for a key."""
        raise NotImplementedError

    def clear(self, key: str) -> None:
        """Forget a key entirely."""
        raise NotImplementedError


class InMemoryLockoutStore(LockoutStore):
    """A lockout store that lives in one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[str, Tuple[int, Optional[datetime]]] = {}

    def record_failure(self, key: str, now: datetime) -> int:
        with self._lock:
            attempts, locked_until = self._state.get(key, (0, None))
            attempts += 1
            self._state[key] = (attempts, locked_until)
            return attempts

    def record_success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def locked_until(self, key: str) -> Optional[datetime]:
        with self._lock:
            return self._state.get(key, (0, None))[1]

    def set_locked_until(self, key: str, until: datetime) -> None:
        with self._lock:
            attempts = self._state.get(key, (0, None))[0]
            self._state[key] = (attempts, until)

    def attempts(self, key: str) -> int:
        with self._lock:
            return self._state.get(key, (0, None))[0]

    def clear(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


class PostgresLockoutStore(LockoutStore):
    """A lockout store that several instances share.

    The row of a key is locked with ``FOR UPDATE`` while it is updated, so
    that two instances counting the same failure at the same moment do not
    lose one of the counts.
    """

    def __init__(self, database: Database):
        self.database = database

    def record_failure(self, key: str, now: datetime) -> int:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO auth_lockout (key, failed_attempts, updated_at)"
                " VALUES (%s, 1, %s) ON CONFLICT (key) DO UPDATE"
                " SET failed_attempts = auth_lockout.failed_attempts + 1,"
                " updated_at = EXCLUDED.updated_at RETURNING failed_attempts",
                (key, now))
            return int(cursor.fetchone()[0])

    def record_success(self, key: str) -> None:
        with self.database.transaction() as cursor:
            cursor.execute(
                "DELETE FROM auth_lockout WHERE key = %s", (key,))

    def locked_until(self, key: str) -> Optional[datetime]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT locked_until FROM auth_lockout WHERE key = %s", (key,))
                row = cursor.fetchone()
                if row is None or row[0] is None:
                    return None
                value = row[0]
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                return value

    def set_locked_until(self, key: str, until: datetime) -> None:
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO auth_lockout (key, failed_attempts, locked_until, updated_at)"
                " VALUES (%s, 0, %s, %s) ON CONFLICT (key) DO UPDATE"
                " SET locked_until = EXCLUDED.locked_until, updated_at = EXCLUDED.updated_at",
                (key, until, datetime.now(timezone.utc)))

    def attempts(self, key: str) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT failed_attempts FROM auth_lockout WHERE key = %s", (key,))
                row = cursor.fetchone()
                return int(row[0]) if row else 0

    def clear(self, key: str) -> None:
        with self.database.transaction() as cursor:
            cursor.execute("DELETE FROM auth_lockout WHERE key = %s", (key,))

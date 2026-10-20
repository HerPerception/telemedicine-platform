"""The accounts and the sessions, in the database.

ENG-007 made the audit log and the lockout counter shared between the
instances of the application. The same argument applies to two more pieces
of state, and both of them are tables that already exist:

* **the accounts.** An account created on one instance has to be known to
  the others, or a patient cannot log in twice.
* **the sessions.** A session issued on one instance has to be accepted by
  the others, or a request that lands on a different instance is refused
  and the patient is asked to sign in again. This is the state that decides
  where a request may be load-balanced to.

The implementations here satisfy the interfaces of ENG-002 — the
``UserRepository`` and the ``SessionStore`` of ``telemedicine.auth`` — so
the service does not know whether it is talking to memory or to a database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from telemedicine.models import Role, Session, UserAccount
from telemedicine.persistence.database import Database


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresUserRepository:
    """The accounts, in the ``user_account`` table."""

    def __init__(self, database: Database):
        self.database = database

    def save(self, account: UserAccount) -> UserAccount:
        """Create the account, or update it if it is already there."""
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO user_account (id, email, password_hash, role, account_ref,"
                " disabled, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " email = EXCLUDED.email, password_hash = EXCLUDED.password_hash,"
                " role = EXCLUDED.role, account_ref = EXCLUDED.account_ref,"
                " disabled = EXCLUDED.disabled, updated_at = EXCLUDED.updated_at",
                (account.user_id, account.email, account.password_hash, account.role.value,
                 account.record_id, account.disabled, account.created_at, _now()))
        return account

    def get_by_email(self, email: str) -> Optional[UserAccount]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, email, password_hash, role, account_ref, disabled, created_at"
                    " FROM user_account WHERE lower(email) = lower(%s)", (email,))
                row = cursor.fetchone()
        return _to_account(row) if row else None

    def get_by_id(self, user_id: str) -> Optional[UserAccount]:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, email, password_hash, role, account_ref, disabled, created_at"
                    " FROM user_account WHERE id = %s", (user_id,))
                row = cursor.fetchone()
        return _to_account(row) if row else None

    def __len__(self) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM user_account")
                return int(cursor.fetchone()[0])


class PostgresSessionStore:
    """The sessions, in the ``auth_session`` table."""

    def __init__(self, database: Database):
        self.database = database

    def save(self, session: Session) -> Session:
        """Create the session, or update it if it is already there."""
        with self.database.transaction() as cursor:
            cursor.execute(
                "INSERT INTO auth_session (id, user_id, token_hash, created_at, expires_at,"
                " revoked_at) VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (id) DO UPDATE SET"
                " token_hash = EXCLUDED.token_hash, expires_at = EXCLUDED.expires_at,"
                " revoked_at = EXCLUDED.revoked_at",
                (session.session_id, session.user_id, session.token_hash, session.created_at,
                 session.expires_at, session.revoked_at))
        return session

    def get(self, token: str) -> Optional[Session]:
        """The session of a token, or None."""
        from telemedicine.security import hash_token
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, user_id, token_hash, created_at, expires_at, revoked_at"
                    " FROM auth_session WHERE token_hash = %s", (hash_token(token),))
                row = cursor.fetchone()
        return _to_session(row) if row else None

    def replace(self, session: Session) -> Session:
        return self.save(session)

    def revoke_for_user(self, user_id: str, now: datetime) -> int:
        """End every session of a user. Returns how many were ended."""
        with self.database.transaction() as cursor:
            cursor.execute(
                "UPDATE auth_session SET revoked_at = %s"
                " WHERE user_id = %s AND revoked_at IS NULL", (now, user_id))
            return cursor.rowcount

    def __len__(self) -> int:
        with self.database.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM auth_session")
                return int(cursor.fetchone()[0])


def _to_account(row) -> UserAccount:
    return UserAccount(
        user_id=str(row[0]),
        email=row[1],
        role=Role(row[3]),
        password_hash=row[2],
        record_id=row[4],
        disabled=bool(row[5]),
        created_at=row[6],
    )


def _to_session(row) -> Session:
    return Session(
        session_id=str(row[0]),
        user_id=str(row[1]),
        token_hash=row[2],
        created_at=row[3],
        expires_at=row[4],
        revoked_at=row[5],
    )

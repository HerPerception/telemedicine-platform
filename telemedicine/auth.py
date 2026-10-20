"""Authentication: accounts, passwords and sessions.

Both roles authenticate through the same path — a patient and a practitioner
are the same kind of account with a different role, and a different set of
authorizations. The service:

* stores passwords as PBKDF2-HMAC-SHA256 hashes, never in the clear;
* issues session tokens that are shown to the caller exactly once and are
  stored only as a SHA-256 digest;
* expires sessions after a fixed lifetime and supports explicit logout;
* writes an audit entry for every account creation and every login attempt,
  successful or not.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional, Tuple

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.errors import AuthenticationError, ValidationError
from telemedicine.models import Role, Session, UserAccount
from telemedicine.security import (
    DEFAULT_ITERATIONS,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)

MIN_PASSWORD_LENGTH = 12
DEFAULT_SESSION_TTL = timedelta(hours=8)

# Audit actions used by this module.
ACTION_ACCOUNT_CREATE = "account.create"
ACTION_LOGIN = "auth.login"
ACTION_LOGOUT = "auth.logout"
ACTION_PASSWORD_CHANGE = "auth.password_change"

UNKNOWN_ACTOR = "anonymous"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    if not isinstance(email, str) or not email.strip():
        raise ValidationError("email is required")
    cleaned = email.strip().lower()
    if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
        raise ValidationError(f"'{email}' is not a valid email address")
    if " " in cleaned:
        raise ValidationError("email must not contain spaces")
    return cleaned


def validate_password(password: str, email: str = "") -> None:
    """Enforce the MVP password policy.

    The policy is deliberately simple and is a floor, not a ceiling: length,
    and the password must not be the account's own email address. Real
    deployments should add breached-password screening, which needs a
    network service the MVP does not have.
    """
    if not isinstance(password, str):
        raise ValidationError("password must be a string")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if email and password.lower() == email.lower():
        raise ValidationError("password must not be the account's email address")


def mask_email(email: str) -> str:
    """Mask an email address for the audit log.

    Audit entries are security records, but they are also read by people who
    do not need the full address of a person who failed to log in.
    """
    if not email or "@" not in email:
        return "unknown"
    local, _, domain = email.partition("@")
    head = local[0] if local else ""
    return f"{head}***@{domain}"


class UserRepository:
    """In-memory account storage.

    The PostgreSQL equivalent is the ``user_account`` table in
    ``db/auth_schema.sql``. Swapping this for a database-backed repository is
    the only change ENG-006 needs to make to persist accounts.
    """

    def __init__(self):
        self._by_email: Dict[str, UserAccount] = {}
        self._by_id: Dict[str, UserAccount] = {}

    def save(self, account: UserAccount) -> UserAccount:
        self._by_email[account.email] = account
        self._by_id[account.user_id] = account
        return account

    def get_by_email(self, email: str) -> Optional[UserAccount]:
        return self._by_email.get(email)

    def get_by_id(self, user_id: str) -> Optional[UserAccount]:
        return self._by_id.get(user_id)

    def __len__(self) -> int:
        return len(self._by_id)


class SessionStore:
    """In-memory session storage, keyed by token digest.

    The raw token is never stored, so this mapping cannot be used to
    impersonate a user even if it leaks.
    """

    def __init__(self):
        self._by_token_hash: Dict[str, Session] = {}

    def save(self, session: Session) -> Session:
        self._by_token_hash[session.token_hash] = session
        return session

    def get(self, token: str) -> Optional[Session]:
        return self._by_token_hash.get(hash_token(token))

    def replace(self, session: Session) -> Session:
        self._by_token_hash[session.token_hash] = session
        return session

    def revoke_for_user(self, user_id: str, now: datetime) -> int:
        """End every session of a user. Returns how many were ended."""
        revoked = 0
        for token_hash, session in list(self._by_token_hash.items()):
            if session.user_id == user_id and session.revoked_at is None:
                self._by_token_hash[token_hash] = replace(session, revoked_at=now)
                revoked += 1
        return revoked

    def __len__(self) -> int:
        return len(self._by_token_hash)


class AuthService:
    """Registration, password authentication and session lifecycle."""

    def __init__(self, users: Optional[UserRepository] = None,
                 audit: Optional[AuditLog] = None,
                 sessions: Optional[SessionStore] = None,
                 *, password_iterations: int = DEFAULT_ITERATIONS,
                 session_ttl: timedelta = DEFAULT_SESSION_TTL,
                 clock: Callable[[], datetime] = _utc_now):
        self.users = users if users is not None else UserRepository()
        self.audit = audit if audit is not None else AuditLog(clock=clock)
        self.sessions = sessions if sessions is not None else SessionStore()
        self.password_iterations = password_iterations
        self.session_ttl = session_ttl
        self._clock = clock
        # A hash of a value nobody knows, used to spend the same time on a
        # login for an account that does not exist as on a login with a
        # wrong password. Without it, the response time tells an attacker
        # which addresses are registered.
        self._decoy_hash = hash_password("not-a-real-password",
                                         iterations=password_iterations)

    # -- accounts ---------------------------------------------------------

    def register(self, email: str, password: str, role: Role,
                 record_id: Optional[str] = None) -> UserAccount:
        """Create an account and return it.

        The returned object carries the password hash; it must never be
        serialised into a response body.
        """
        if not isinstance(role, Role):
            raise ValidationError("role must be a Role")
        normalized = normalize_email(email)
        validate_password(password, normalized)
        if self.users.get_by_email(normalized) is not None:
            raise ValidationError(f"an account already exists for '{normalized}'")
        account = UserAccount(
            user_id=str(uuid.uuid4()),
            email=normalized,
            role=role,
            password_hash=hash_password(password, iterations=self.password_iterations),
            record_id=record_id,
            created_at=self._clock(),
        )
        self.users.save(account)
        self.audit.append(
            actor_user_id=account.user_id,
            actor_role=account.role.value,
            action=ACTION_ACCOUNT_CREATE,
            resource_type="user_account",
            resource_id=account.user_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"account created for role {role.value}",
        )
        return account

    def get_account(self, user_id: str) -> UserAccount:
        account = self.users.get_by_id(user_id)
        if account is None:
            raise AuthenticationError("unknown account")
        return account

    def set_password(self, account: UserAccount, current_password: str,
                     new_password: str) -> UserAccount:
        """Change a password, requiring the current one."""
        if not verify_password(current_password, account.password_hash):
            self.audit.append(
                actor_user_id=account.user_id,
                actor_role=account.role.value,
                action=ACTION_PASSWORD_CHANGE,
                resource_type="user_account",
                resource_id=account.user_id,
                outcome=OUTCOME_DENIED,
                detail="current password did not match",
            )
            raise AuthenticationError("current password is incorrect")
        validate_password(new_password, account.email)
        updated = replace(
            account,
            password_hash=hash_password(new_password, iterations=self.password_iterations),
        )
        self.users.save(updated)
        # A password change ends every session of that account, including the
        # one the change was made with: whoever asked for the change should
        # have to sign in again.
        revoked = self.sessions.revoke_for_user(account.user_id, self._clock())
        self.audit.append(
            actor_user_id=account.user_id,
            actor_role=account.role.value,
            action=ACTION_PASSWORD_CHANGE,
            resource_type="user_account",
            resource_id=account.user_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"password changed; {revoked} session(s) revoked",
        )
        return updated

    def disable(self, account: UserAccount) -> UserAccount:
        """Disable an account. A disabled account cannot log in or use a session."""
        updated = replace(account, disabled=True)
        self.users.save(updated)
        return updated

    # -- authentication ---------------------------------------------------

    def authenticate(self, email: str, password: str) -> UserAccount:
        """Verify an email and password.

        Raises :class:`~telemedicine.errors.AuthenticationError` for every
        failure — unknown account, wrong password, disabled account — so that
        the caller cannot tell the difference and probe for valid accounts.
        Every attempt is audited.
        """
        normalized = ""
        try:
            normalized = normalize_email(email)
        except ValidationError:
            self._audit_login_failure(UNKNOWN_ACTOR, "unknown", email or "",
                                      "malformed email address")
            raise AuthenticationError("invalid credentials") from None

        account = self.users.get_by_email(normalized)
        if account is None:
            # Spend the same time as a real verification, so that the
            # response does not reveal whether the account exists.
            verify_password(password, self._decoy_hash)
            self._audit_login_failure(UNKNOWN_ACTOR, "unknown", normalized,
                                      "no such account")
            raise AuthenticationError("invalid credentials")

        if not verify_password(password, account.password_hash):
            self._audit_login_failure(account.user_id, account.role.value, normalized,
                                      "password did not match")
            raise AuthenticationError("invalid credentials")

        if not account.is_active:
            self._audit_login_failure(account.user_id, account.role.value, normalized,
                                      "account is disabled")
            raise AuthenticationError("invalid credentials")

        self.audit.append(
            actor_user_id=account.user_id,
            actor_role=account.role.value,
            action=ACTION_LOGIN,
            resource_type="user_account",
            resource_id=account.user_id,
            outcome=OUTCOME_SUCCESS,
            detail="password authentication succeeded",
        )
        return account

    def _audit_login_failure(self, actor_user_id: str, actor_role: str, email: str,
                              detail: str) -> None:
        self.audit.append(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action=ACTION_LOGIN,
            resource_type="user_account",
            resource_id=actor_user_id,
            outcome=OUTCOME_DENIED,
            detail=f"{detail} ({mask_email(email)})",
        )

    # -- sessions ---------------------------------------------------------

    def create_session(self, account: UserAccount) -> Tuple[str, Session]:
        """Issue a session and return ``(token, session)``.

        The token is returned once and is not recoverable afterwards; the
        store keeps only its digest.
        """
        # The caller may hold a stale copy of the account, so the current
        # state is re-read from the repository before the decision.
        current = self.users.get_by_id(account.user_id) or account
        if not current.is_active:
            raise AuthenticationError("the account is disabled")
        token = generate_token()
        now = self._clock()
        session = Session(
            session_id=str(uuid.uuid4()),
            user_id=current.user_id,
            token_hash=hash_token(token),
            created_at=now,
            expires_at=now + self.session_ttl,
        )
        self.sessions.save(session)
        return token, session

    def authenticate_session(self, token: str) -> UserAccount:
        """Return the account behind a session token.

        Raises :class:`~telemedicine.errors.AuthenticationError` for an
        unknown, revoked or expired token.
        """
        session = self.sessions.get(token) if token else None
        if session is None:
            raise AuthenticationError("invalid session")
        if session.is_revoked:
            raise AuthenticationError("the session has been revoked")
        now = self._clock()
        if session.is_expired(now):
            raise AuthenticationError("the session has expired")
        account = self.users.get_by_id(session.user_id)
        if account is None or not account.is_active:
            raise AuthenticationError("invalid session")
        return account

    def revoke_session(self, token: str) -> None:
        """End a session (logout). Revoking an unknown token is not an error."""
        session = self.sessions.get(token) if token else None
        if session is None:
            return
        self.sessions.replace(replace(session, revoked_at=self._clock()))
        account = self.users.get_by_id(session.user_id)
        self.audit.append(
            actor_user_id=session.user_id,
            actor_role=account.role.value if account else "unknown",
            action=ACTION_LOGOUT,
            resource_type="user_account",
            resource_id=session.user_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"session {session.session_id} revoked",
        )

"""Password hashing and token handling.

Everything here uses the standard library only:

* passwords are hashed with PBKDF2-HMAC-SHA256 and a per-password random
  salt; the encoded form carries the algorithm, the iteration count, the salt
  and the hash so the parameters can be raised later without a migration;
* verification is constant-time;
* session tokens are generated with :mod:`secrets` and are never stored —
  only their SHA-256 digest is, so a database leak does not yield usable
  tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16
TOKEN_BYTES = 32


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS, salt: bytes = None) -> str:
    """Hash a password and return its encoded form.

    The encoded form is ``pbkdf2_sha256$<iterations>$<salt>$<hash>`` with the
    salt and hash base64url-encoded. The iteration count is stored so that the
    cost can be increased for future hashes while old ones keep verifying.
    """
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if salt is None:
        salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against an encoded hash in constant time.

    Returns ``False`` rather than raising for malformed or missing hashes, so
    that a corrupt row fails the login instead of crashing the request.
    """
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != ALGORITHM:
        return False
    try:
        iterations = int(parts[1])
        salt = _b64decode(parts[2])
        expected = _b64decode(parts[3])
    except (ValueError, TypeError):
        return False
    if iterations < 1:
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def generate_token(nbytes: int = TOKEN_BYTES) -> str:
    """Generate a random, URL-safe session token."""
    if nbytes < 16:
        raise ValueError("tokens must have at least 16 bytes of entropy")
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Return the digest that is stored for a session token.

    A plain SHA-256 digest is enough here: the token is already high-entropy
    random data, so there is nothing to brute-force.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two strings without leaking their contents through timing."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))

"""Signing in and out over HTTP.

Until now the authentication service existed but there was **no way to reach
it over HTTP**: a client had no way of getting a session token, and the
whole API was unusable by anything but the tests. These are the endpoints
that fix that.

They are shared by both surfaces — the FHIR API and the video rooms — so
that a client signs in once and uses the token for both.

The source address of the request is passed to the authentication service,
because the lockout needs it: a password-guessing attack from one address
and a distributed attack from many look the same to the account, and only
the address tells them apart.
"""

from __future__ import annotations

import json
from typing import Optional

from telemedicine.auth import AuthService
from telemedicine.errors import AuthenticationError, ValidationError

# The header the HTTP server sets with the address the request came from.
HEADER_CLIENT_ADDRESS = "x-client-address"
HEADER_FORWARDED_FOR = "x-forwarded-for"


class SessionEndpoints:
    """The session endpoints, mixed into an HTTP application."""

    def __init__(self, auth: AuthService, trust_forwarded_for: bool = False):
        self.auth = auth
        # Whether to believe the address a proxy says the request came from.
        # It is only safe behind a proxy that replaces the header, so it is
        # off unless a deployment asks for it.
        self.trust_forwarded_for = trust_forwarded_for

    # -- the endpoints -----------------------------------------------------

    def handle_session(self, method: str, path: str, headers: dict,
                       body: bytes):
        """Handle ``POST`` and ``DELETE`` on the session endpoint."""
        if method == "POST":
            return self.sign_in(headers, body)
        if method == "DELETE":
            return self.sign_out(headers)
        return None

    def sign_in(self, headers: dict, body: bytes):
        """Sign in and return a session token."""
        payload = _parse(body)
        email = payload.get("email")
        password = payload.get("password")
        if not email or not password:
            raise ValidationError("an email address and a password are required")

        account = self.auth.authenticate(email, password, source=self.source(headers))
        token, session = self.auth.create_session(account)
        return {
            "token": token,
            "user_id": account.user_id,
            "role": account.role.value,
            "expires_at": session.expires_at.isoformat().replace("+00:00", "Z"),
        }

    def sign_out(self, headers: dict):
        """End the session the request is made with."""
        token = _bearer(headers)
        self.auth.revoke_session(token)
        return None

    # -- the source address ------------------------------------------------

    def source(self, headers: dict) -> Optional[str]:
        """The address the request came from, if the server told us."""
        if self.trust_forwarded_for:
            forwarded = headers.get(HEADER_FORWARDED_FOR)
            if forwarded:
                # The left-most address is the one the client used.
                return forwarded.split(",")[0].strip()
        return headers.get(HEADER_CLIENT_ADDRESS)


def _parse(body: bytes) -> dict:
    if not body:
        raise ValidationError("a request body is required")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"the body is not valid JSON: {error}") from None
    if not isinstance(payload, dict):
        raise ValidationError("the body must be a JSON object")
    return payload


def _bearer(headers: dict) -> str:
    header = headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise AuthenticationError("a session token is required")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise AuthenticationError("a session token is required")
    return token

"""The SMART-on-FHIR endpoints.

**They only exist when SMART is switched on.** With the flag off, the
application is not mounted at all, and the ordinary sign-in is the only way
in — which is how the MVP works, and how a practice with no hospital
connection works.

With the flag on, three endpoints:

``GET /.well-known/smart-configuration``
    how a record finds out where to send the browser.

``GET /smart/authorize``
    the application sends the browser to the record's own authorization
    endpoint, with the scopes, a signed state, and a PKCE challenge.

``GET /smart/callback``
    the record sends the browser back with a code. The application checks
    the state, exchanges the code for a token at the record, asks the record
    who the clinician is, maps that to a local account, and signs them in.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

from telemedicine.auth import AuthService
from telemedicine.errors import AuthenticationError, ValidationError
from telemedicine.smart import (
    DISCOVERY_PATH,
    SmartConfiguration,
    SmartError,
    SmartNotConfigured,
    discovery_document,
    exchange_code,
    fetch_identity,
    start_flow,
    verify_state,
)

APPLICATION_JSON = "application/json; charset=utf-8"


class SmartApplication:
    """The SMART endpoints, when they are switched on."""

    def __init__(self, configuration: SmartConfiguration, auth: AuthService,
                 state_secret: str, base_path: str = "",
                 trust_forwarded_for: bool = False):
        self.configuration = configuration
        self.auth = auth
        self.state_secret = state_secret
        self.base_path = base_path.rstrip("/")
        self.trust_forwarded_for = trust_forwarded_for

    # -- the entry point ---------------------------------------------------

    def handle(self, method: str, path: str, query: Optional[Dict] = None,
               headers: Optional[Dict[str, str]] = None,
               body: bytes = b"") -> "Response":
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        query = query or {}
        try:
            return self._dispatch(method, path, query, headers)
        except SmartNotConfigured as error:
            return self._json(404, {"error": "not_configured", "message": str(error)})
        except SmartError as error:
            return self._json(400, {"error": "smart_error", "message": str(error)})
        except AuthenticationError as error:
            return self._json(401, {"error": "login", "message": str(error)})

    def _dispatch(self, method: str, path: str, query, headers) -> "Response":
        remainder = path[len(self.base_path):].strip("/") if self.base_path else path.strip("/")
        if remainder == DISCOVERY_PATH.strip("/"):
            if method != "GET":
                return self._json(405, {"error": "not_supported",
                                        "message": f"{method} is not supported here"})
            return self._json(200, discovery_document(self.configuration))
        if remainder == "smart/authorize":
            if method != "GET":
                return self._json(405, {"error": "not_supported",
                                        "message": f"{method} is not supported here"})
            return self._authorize(query)
        if remainder == "smart/callback":
            if method != "GET":
                return self._json(405, {"error": "not_supported",
                                        "message": f"{method} is not supported here"})
            return self._callback(query)
        return self._json(404, {"error": "not_found",
                                "message": f"no endpoint at '{path}'"})

    # -- the operations ----------------------------------------------------

    def _authorize(self, query) -> "Response":
        """Send the browser to the record."""
        launch = _first(query, "launch")
        _state, url = start_flow(self.configuration, self.state_secret, launch=launch)
        return Response(status=302, body=b"", headers={"Location": url})

    def _callback(self, query) -> "Response":
        """The record has sent the browser back with a code."""
        code = _first(query, "code")
        state = _first(query, "state")
        if not code:
            raise SmartError("the record sent no code")
        payload = verify_state(state, self.state_secret)
        verifier = payload.get("code_verifier", "")
        if not verifier:
            raise SmartError("the state carries no verifier")

        token = exchange_code(self.configuration, code, verifier)
        identity = fetch_identity(self.configuration, token["access_token"])

        account_id = self.configuration.account_for(identity)
        if not account_id:
            raise SmartError(
                f"'{identity}' is not one of this practice's accounts. The "
                "practice has to say who its clinicians are, in "
                "config/smart_clients.yaml")
        account = self.auth.users.get_by_id(account_id)
        if account is None:
            raise SmartError(f"the account '{account_id}' does not exist")

        session_token, session = self.auth.create_session(account)
        return self._json(200, {
            "token": session_token,
            "user_id": account.user_id,
            "role": account.role.value,
            "identity": identity,
            "expires_at": session.expires_at.isoformat().replace("+00:00", "Z"),
        })

    def _json(self, status: int, payload: dict) -> "Response":
        return Response(
            status=status,
            body=json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": APPLICATION_JSON,
                     "Cache-Control": "no-store, no-cache, must-revalidate, private"},
        )


class Response:
    """One HTTP response."""

    def __init__(self, status: int, body: bytes, headers: Optional[Dict[str, str]] = None):
        self.status = status
        self.body = body
        self.headers = dict(headers or {})


def _first(query: Dict, name: str) -> str:
    """One value of a query parameter."""
    value = query.get(name)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value).strip() if value else ""

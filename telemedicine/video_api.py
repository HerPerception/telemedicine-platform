"""The HTTP surface of the video consultation rooms.

The FHIR API of ENG-006 is a standards-based API for clinical data; the
video rooms are not a FHIR resource, so they get their own small surface
under ``/video`` with its own error shape.

The error shape matters most here. A client that cannot join has to know
*why* and *whether to try again*:

.. code-block:: json

    {"error": "room_not_open_yet",
     "message": "the consultation room opens 15 minutes before the appointment",
     "retryable": true,
     "retry_after_seconds": 412}

The status codes are: ``400`` a malformed request, ``401`` no session, ``403``
the caller is not in this room, ``404`` no such room or appointment, ``405``
the method is not supported, and ``409`` the room cannot be joined yet —
with the reason and the retry path in the body.
"""

from __future__ import annotations

import json
from typing import Dict, Optional

from telemedicine.auth import AuthService
from telemedicine.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    TelemedicineError,
    ValidationError,
)
from telemedicine.fhir.server import Response
from telemedicine.session_api import SessionEndpoints
from telemedicine.video import JoinUnavailable, VideoService

CONTENT_TYPE = "application/json; charset=utf-8"


class VideoApplication:
    """Routes a request to the video service and builds the response."""

    def __init__(self, service: VideoService, auth: AuthService, base_path: str = "/video",
                 trust_forwarded_for: bool = False):
        self.service = service
        self.auth = auth
        self.base_path = base_path.rstrip("/")
        # Signing in and out, and the address the request came from.
        self.sessions = SessionEndpoints(auth, trust_forwarded_for=trust_forwarded_for)

    # -- the entry point ---------------------------------------------------

    def handle(self, method: str, path: str, query: Optional[Dict] = None,
               headers: Optional[Dict[str, str]] = None, body: bytes = b"") -> Response:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        try:
            return self._dispatch(method, path, headers, body)
        except AuthenticationError as error:
            return self._error(401, "login", str(error), authenticate=True)
        except AuthorizationError as error:
            return self._error(403, "forbidden", str(error))
        except JoinUnavailable as error:
            return self._error(409, error.reason, str(error), retryable=error.retryable,
                                retry_after_seconds=error.retry_after_seconds)
        except NotFoundError as error:
            return self._error(404, "not_found", str(error))
        except ConflictError as error:
            return self._error(409, "conflict", str(error))
        except ValidationError as error:
            return self._error(400, "invalid", str(error))
        except TelemedicineError as error:
            return self._error(500, "exception", str(error))

    # -- routing -----------------------------------------------------------

    def _dispatch(self, method: str, path: str, headers, body) -> Response:
        if not path.startswith(self.base_path):
            return self._error(404, "not_found", f"no endpoint at '{path}'")
        remainder = path[len(self.base_path):].strip("/")
        segments = [segment for segment in remainder.split("/") if segment]

        # The session endpoints come before the authentication: signing in is
        # how a caller gets the token in the first place.
        if not segments or segments[0] == "session":
            if method == "POST":
                return self._json(201, self.sessions.sign_in(headers, body))
            if method == "DELETE":
                self.sessions.sign_out(headers)
                return Response(status=204, body=b"", headers={})
            return self._method_not_allowed(method)

        actor = self._authenticate(headers)

        if segments[0] != "rooms":
            return self._error(404, "not_found", f"no endpoint at '{path}'")

        if len(segments) == 1:
            if method != "POST":
                return self._method_not_allowed(method)
            return self._open_room(actor, body)

        room_id = segments[1]
        if len(segments) == 2:
            if method != "GET":
                return self._method_not_allowed(method)
            return self._json(200, self.service.room_state(actor, room_id))

        action = segments[2]
        if action == "join":
            if method != "POST":
                return self._method_not_allowed(method)
            return self._join(actor, room_id)
        if action == "admit":
            if method != "POST":
                return self._method_not_allowed(method)
            return self._admit(actor, room_id, body)
        if action == "token":
            if method != "GET":
                return self._method_not_allowed(method)
            return self._token(actor, room_id)
        return self._error(404, "not_found", f"no endpoint at '{path}'")

    # -- the operations ----------------------------------------------------

    def _open_room(self, actor, body: bytes) -> Response:
        payload = self._parse(body)
        appointment_id = payload.get("appointment")
        if not appointment_id:
            raise ValidationError("the body must name the appointment")
        room = self.service.open_room(actor, appointment_id)
        return self._json(201, {
            "room_id": room.room_id,
            "appointment_id": room.appointment_id,
            "status": room.status,
            "starts_at": room.starts_at.isoformat().replace("+00:00", "Z"),
            "ends_at": room.ends_at.isoformat().replace("+00:00", "Z"),
        })

    def _join(self, actor, room_id: str) -> Response:
        result = self.service.join(actor, room_id)
        payload = {
            "room_id": result.room_id,
            "status": result.status,
            "admitted": result.admitted,
            "retryable": result.retryable,
        }
        if result.retry_after_seconds is not None:
            payload["retry_after_seconds"] = result.retry_after_seconds
        if result.token:
            payload["token"] = result.token
        return self._json(200, payload)

    def _admit(self, actor, room_id: str, body: bytes) -> Response:
        payload = self._parse(body)
        participant = payload.get("participant")
        if not participant:
            raise ValidationError("the body must name the participant")
        room = self.service.admit(actor, room_id, participant)
        return self._json(200, {
            "room_id": room.room_id,
            "participants": [
                {"user_id": user_id, "status": status} for user_id, status in room.participants
            ],
        })

    def _token(self, actor, room_id: str) -> Response:
        token = self.service.issue_join_token(actor, room_id)
        return self._json(200, {
            "room_id": token.room_id,
            "token": token.token,
            "expires_at": token.expires_at.isoformat().replace("+00:00", "Z"),
            "expires_in": token.expires_in(self.service._clock()),
        })

    # -- helpers -----------------------------------------------------------

    def _authenticate(self, headers: Dict[str, str]):
        header = headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthenticationError("a session token is required")
        token = header.split(" ", 1)[1].strip()
        if not token:
            raise AuthenticationError("a session token is required")
        return self.auth.authenticate_session(token)

    def _parse(self, body: bytes) -> dict:
        if not body:
            raise ValidationError("a request body is required")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"the body is not valid JSON: {error}") from None
        if not isinstance(payload, dict):
            raise ValidationError("the body must be a JSON object")
        return payload

    def _method_not_allowed(self, method: str) -> Response:
        return self._error(405, "not_supported", f"{method} is not supported here")

    def _error(self, status: int, code: str, message: str, *,
               retryable: bool = False, retry_after_seconds: Optional[int] = None,
               authenticate: bool = False) -> Response:
        payload = {"error": code, "message": message, "retryable": retryable}
        if retry_after_seconds is not None:
            payload["retry_after_seconds"] = retry_after_seconds
        response = self._json(status, payload)
        if authenticate:
            response.headers["WWW-Authenticate"] = 'Bearer realm="telemedicine"'
        return response

    def _json(self, status: int, payload: dict) -> Response:
        return Response(
            status=status,
            body=json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": CONTENT_TYPE,
                "Cache-Control": "no-store, no-cache, must-revalidate, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )

"""The HTTP surface of the FHIR R4 API.

The server is deliberately small and standard-library only: it routes a
request to the repository, which authorizes it and audits it, and it turns
the domain's errors into the right HTTP status with an ``OperationOutcome``
body.

The status codes it uses:

===========  ===========================================================
``400``      the request body or the parameters are not valid FHIR
``401``      no session, or a session that is not valid
``403``      the caller may not do that
``404``      no such resource
``405``      the method is not supported — a clinical record is never
             deleted
``409``      the request conflicts with the state of the data, such as
             booking a slot that has just been taken
``500``      the server produced a resource that does not satisfy the
             profile, which is a defect rather than a client error
===========  ===========================================================

Every resource that goes out is checked against the profile this project
publishes, so a response that would not satisfy the mapping is never sent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from telemedicine.auth import AuthService
from telemedicine.consent_api import ConsentEndpoints
from telemedicine.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    TelemedicineError,
    ValidationError,
)
from telemedicine.fhir import serialization
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.validation import validate_resource
from telemedicine.session_api import SessionEndpoints

RESOURCE_TYPES = {
    "Patient": "patient",
    "Practitioner": "practitioner",
    "Appointment": "appointment",
    "Encounter": "encounter",
    "MedicationRequest": "medication_request",
}


@dataclass
class Response:
    """One HTTP response."""

    status: int
    body: bytes
    headers: Dict[str, str] = field(default_factory=dict)


class FhirApplication:
    """Routes a request to the repository and builds the response."""

    def __init__(self, repository: FhirRepository, auth: AuthService,
                 base_path: str = "/fhir", trust_forwarded_for: bool = False,
                 consent=None):
        self.repository = repository
        self.auth = auth
        self.base_path = base_path.rstrip("/")
        # Signing in and out, and the address the request came from.
        self.sessions = SessionEndpoints(auth, trust_forwarded_for=trust_forwarded_for)
        # The consent endpoints. They are optional here so that a caller
        # that only wants the clinical API does not have to build a consent
        # service; the endpoint then says that it is not configured rather
        # than pretending that nobody has consented to anything.
        self.consent = ConsentEndpoints(consent) if consent is not None else None

    # -- the entry point ---------------------------------------------------

    def handle(self, method: str, path: str, query: Optional[Dict] = None,
               headers: Optional[Dict[str, str]] = None,
               body: bytes = b"") -> Response:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        query = query or {}
        try:
            return self._dispatch(method, path, query, headers, body)
        except AuthenticationError as error:
            return self._outcome(401, "login", str(error), authenticate=True)
        except AuthorizationError as error:
            # The reason a caller was refused is in the audit log, which the
            # caller cannot read. The response says what happened, not why:
            # a detailed reason would tell an unauthorised caller whether the
            # resource exists and who it belongs to.
            detail = "not permitted"
            if error.action and error.resource_type:
                detail = f"not permitted: {error.action} on {error.resource_type}"
            return self._outcome(403, "forbidden", detail)
        except ConflictError as error:
            return self._outcome(409, "conflict", str(error))
        except NotFoundError as error:
            return self._outcome(404, "not-found", str(error))
        except ValidationError as error:
            return self._outcome(400, "invalid", str(error))
        except TelemedicineError as error:
            return self._outcome(500, "exception", str(error))

    # -- routing -----------------------------------------------------------

    def _dispatch(self, method: str, path: str, query, headers, body) -> Response:
        if not path.startswith(self.base_path):
            return self._outcome(404, "not-found", f"no endpoint at '{path}'")
        remainder = path[len(self.base_path):].strip("/")

        if remainder in ("", "metadata"):
            if method != "GET":
                return self._method_not_allowed(method)
            return self._json(200, serialization.capability_statement())

        if remainder == "session":
            if method == "POST":
                return self._json(201, self.sessions.sign_in(headers, body))
            if method == "DELETE":
                self.sessions.sign_out(headers)
                return Response(status=204, body=b"", headers={})
            return self._method_not_allowed(method)

        if remainder == "consent" or remainder.startswith("consent/"):
            return self._consent(method, remainder, query, headers, body)

        segments = [segment for segment in remainder.split("/") if segment]
        resource_type = segments[0]
        if resource_type not in RESOURCE_TYPES:
            return self._outcome(404, "not-found", f"unknown resource type '{resource_type}'")
        resource_id = segments[1] if len(segments) > 1 else None

        actor = self._authenticate(headers)

        if method == "GET":
            if resource_id is None:
                return self._search(actor, resource_type)
            return self._read(actor, resource_type, resource_id)
        if method == "POST":
            if resource_id is not None:
                return self._outcome(405, "not-supported",
                                     "a resource is created on the type, not on an id")
            return self._create(actor, resource_type, body)
        if method == "PUT":
            if resource_id is None:
                return self._outcome(405, "not-supported",
                                     "an update needs the id of the resource")
            return self._update(actor, resource_type, resource_id, body)
        if method == "DELETE":
            # Clinical data is never deleted. A cancellation is expressed with
            # a status, and the record stays.
            return self._outcome(
                405, "not-supported",
                "clinical records are never deleted; change the status instead")
        return self._method_not_allowed(method)

    # -- the operations ----------------------------------------------------

    def _consent(self, method: str, remainder: str, query, headers,
                 body) -> Response:
        """The consent endpoints.

        What a patient has agreed to, and what they have withdrawn. A
        clinician may read the state of a patient they treat; nobody but the
        patient may change it.
        """
        if self.consent is None:
            return self._outcome(404, "not-found",
                                 "the consent service is not configured")
        actor = self._authenticate(headers)
        status, payload = self.consent.handle(method, remainder, query, actor, body)
        if status == 204:
            # No content, but the same headers as every other response: a
            # consent decision is personal data too.
            response = self._json(204, {})
            response.body = b""
            return response
        return self._json(status, payload)

    def _read(self, actor, resource_type: str, resource_id: str) -> Response:
        if resource_id not in self.repository.known_ids().get(resource_type, set()):
            return self._outcome(404, "not-found",
                                 f"no {resource_type} with id '{resource_id}'")
        domain_object = self._read_domain(actor, resource_type, resource_id)
        resource = self._serialize(resource_type, domain_object)
        return self._resource_response(200, resource)

    def _search(self, actor, resource_type: str) -> Response:
        resources = self._search_domain(actor, resource_type)
        entries = []
        for domain_object in resources:
            resource = self._serialize(resource_type, domain_object)
            errors = validate_resource(resource, self.repository.known_ids(), resource_type)
            if errors:
                return self._outcome(500, "exception", "; ".join(errors))
            entries.append({"resource": resource})
        bundle = {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": len(entries),
            "entry": entries,
        }
        return self._json(200, bundle)

    def _create(self, actor, resource_type: str, body: bytes) -> Response:
        resource = self._parse(body, resource_type)
        domain_object = self._create_domain(actor, resource_type, resource)
        created = self._serialize(resource_type, domain_object)
        location = f"{self.base_path}/{resource_type}/{created.get('id', '')}"
        return self._resource_response(201, created, extra_headers={"Location": location})

    def _update(self, actor, resource_type: str, resource_id: str, body: bytes) -> Response:
        if resource_id not in self.repository.known_ids().get(resource_type, set()):
            return self._outcome(404, "not-found",
                                 f"no {resource_type} with id '{resource_id}'")
        resource = self._parse(body, resource_type)
        domain_object = self._update_domain(actor, resource_type, resource_id, resource)
        updated = self._serialize(resource_type, domain_object)
        return self._resource_response(200, updated)

    # -- the domain calls --------------------------------------------------

    def _read_domain(self, actor, resource_type: str, resource_id: str):
        if resource_type == "Patient":
            return self.repository.read_patient(actor, resource_id)
        if resource_type == "Practitioner":
            return self.repository.read_practitioner(actor, resource_id)
        if resource_type == "Appointment":
            return self.repository.read_appointment(actor, resource_id)
        if resource_type == "Encounter":
            return self.repository.read_encounter(actor, resource_id)
        return self.repository.read_medication_request(actor, resource_id)

    def _search_domain(self, actor, resource_type: str) -> List:
        if resource_type == "Patient":
            return self.repository.search_patients(actor)
        if resource_type == "Practitioner":
            return self.repository.search_practitioners(actor)
        if resource_type == "Appointment":
            return self.repository.search_appointments(actor)
        if resource_type == "Encounter":
            return self.repository.search_encounters(actor)
        return self.repository.search_medication_requests(actor)

    def _create_domain(self, actor, resource_type: str, resource: dict):
        if resource_type == "Appointment":
            return self.repository.create_appointment(actor, resource)
        if resource_type == "Encounter":
            return self.repository.create_encounter(actor, resource)
        if resource_type == "MedicationRequest":
            return self.repository.create_medication_request(actor, resource)
        raise ValidationError(f"a {resource_type} cannot be created through this API")

    def _update_domain(self, actor, resource_type: str, resource_id: str, resource: dict):
        if resource_type == "Patient":
            return self.repository.update_patient(actor, resource_id, resource)
        if resource_type == "Practitioner":
            return self.repository.update_practitioner(actor, resource_id, resource)
        if resource_type == "Appointment":
            return self.repository.update_appointment(actor, resource_id, resource)
        if resource_type == "Encounter":
            return self.repository.update_encounter(actor, resource_id, resource)
        return self.repository.update_medication_request(actor, resource_id, resource)

    # -- helpers -----------------------------------------------------------

    def _authenticate(self, headers: Dict[str, str]):
        header = headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise AuthenticationError("a session token is required")
        token = header.split(" ", 1)[1].strip()
        if not token:
            raise AuthenticationError("a session token is required")
        return self.auth.authenticate_session(token)

    def _parse(self, body: bytes, resource_type: str) -> dict:
        if not body:
            raise ValidationError("a request body is required")
        try:
            resource = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError(f"the body is not valid JSON: {error}") from None
        if not isinstance(resource, dict):
            raise ValidationError("the body must be a JSON object")
        if resource.get("resourceType") != resource_type:
            raise ValidationError(
                f"the body is a {resource.get('resourceType')}, not a {resource_type}")
        return resource

    def _serialize(self, resource_type: str, domain_object) -> dict:
        if resource_type == "Patient":
            return serialization.patient_resource(domain_object)
        if resource_type == "Practitioner":
            return serialization.practitioner_resource(domain_object)
        if resource_type == "Appointment":
            return serialization.appointment_resource(domain_object)
        if resource_type == "Encounter":
            return serialization.encounter_resource(domain_object)
        return serialization.medication_request_resource(domain_object)

    def _resource_response(self, status: int, resource: dict,
                           extra_headers: Optional[Dict[str, str]] = None) -> Response:
        errors = validate_resource(resource, self.repository.known_ids(),
                                    resource.get("resourceType", "resource"))
        if errors:
            # A resource that does not satisfy the profile is never sent.
            return self._outcome(500, "exception", "; ".join(errors))
        response = self._json(status, resource)
        response.headers.update(extra_headers or {})
        return response

    def _outcome(self, status: int, code: str, diagnostics: str,
                 authenticate: bool = False) -> Response:
        body = serialization.operation_outcome(
            "error" if status >= 400 else "information", code, diagnostics)
        response = self._json(status, body)
        if authenticate:
            response.headers["WWW-Authenticate"] = 'Bearer realm="telemedicine"'
        return response

    def _method_not_allowed(self, method: str) -> Response:
        return self._outcome(405, "not-supported", f"{method} is not supported here")

    def _json(self, status: int, payload: dict) -> Response:
        return Response(
            status=status,
            body=json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": serialization.FHIR_CONTENT_TYPE,
                # A response may hold a patient's record. No intermediary and
                # no browser may keep a copy of it.
                "Cache-Control": "no-store, no-cache, must-revalidate, private",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )


# --------------------------------------------------------------------------
# The HTTP server
# --------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    """Glue between the HTTP server and the application."""

    server_version = "telemedicine-fhir/0.1"
    application: FhirApplication = None  # type: ignore[assignment]

    def do_GET(self):  # noqa: N802 - the name is fixed by the base class
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self):  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self):  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        headers = dict(self.headers)
        # The address the request came from, which the lockout needs. It is
        # the socket address, unless a proxy is trusted to say otherwise.
        try:
            headers["x-client-address"] = self.client_address[0]
        except (AttributeError, IndexError):  # pragma: no cover - defensive
            pass
        response = self.application.handle(
            method, parsed.path, parse_qs(parsed.query), headers, body)
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format, *args):  # noqa: A002 - the name is fixed
        """Keep the console quiet; the audit log is the record of what happened."""


class ApplicationRouter:
    """Sends a request to the application that owns its path.

    The FHIR API is served under ``/fhir`` and the video rooms under
    ``/video``; they are separate applications with different error shapes,
    and one server can serve both.
    """

    def __init__(self, applications: Dict[str, object]):
        self.applications = dict(applications)

    def handle(self, method: str, path: str, query=None, headers=None, body=b"") -> Response:
        for prefix, application in sorted(self.applications.items(),
                                          key=lambda item: -len(item[0])):
            if not prefix or path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                return application.handle(method, path, query, headers, body)
        return Response(
            status=404,
            body=json.dumps({"error": "not_found",
                             "message": f"no endpoint at '{path}'"}).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )


def make_server(applications, host: str = "127.0.0.1",
                port: int = 8080) -> ThreadingHTTPServer:
    """Build a server for one application, or for a set of them.

    ``applications`` is either an application, or a mapping of path prefix to
    application.
    """
    if isinstance(applications, dict):
        router = ApplicationRouter(applications)
    else:
        router = ApplicationRouter({getattr(applications, "base_path", ""): applications})
    handler = type("BoundHandler", (_Handler,), {"application": router})
    return ThreadingHTTPServer((host, port), handler)


def serve(applications, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Serve until interrupted."""
    server = make_server(applications, host, port)
    prefixes = ", ".join(sorted(getattr(applications, "base_path", "")
                                if not isinstance(applications, dict) else applications))
    print(f"listening on http://{host}:{port} ({prefixes})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

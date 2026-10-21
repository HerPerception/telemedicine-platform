"""The consent endpoints.

Section 35 of the Nigeria Data Protection Act 2023 says that a data subject
has the right to withdraw consent at any time, and that "the data controller
shall ensure that it is as easy for the data subject to withdraw, as to give
consent". A right that can only be exercised by writing to the practice, or
by ringing it, is not a right that is easy to exercise — so withdrawal is a
request here, in the same way that granting a consent was.

The endpoints:

=========================================  ==========================================
``GET    /fhir/consent``                    the caller's own consent state
``GET    /fhir/consent?patient=<id>``       a patient's state, for a clinician who
                                            treats them
``POST   /fhir/consent/notice``             record that the notice was shown
``POST   /fhir/consent/<purpose>``          grant a consent for one optional purpose
``DELETE /fhir/consent/<purpose>``          withdraw it
=========================================  ==========================================

They live under the FHIR API because they are about the caller's own
account, in the same way the session endpoint is, and because a client
already talks to one base path.

**A clinician may read the state of a patient they treat, and may change
nothing.** They have to know whether a patient agreed before they use a
record for a research purpose — that is the whole point of capturing the
consent. What they may not do is grant or withdraw it: consent is the
patient's own act, and a clinician who could press the button on their
behalf could take it away as well.

**A consent has to name the version of the notice the patient saw.** A
consent that cannot be tied to the words that were read is a consent nobody
can show was informed, which is the thing the Act is asking for.
"""

from __future__ import annotations

import json
from typing import Dict, Optional, Tuple

from telemedicine.consent import OPTIONAL_PURPOSES, ConsentService
from telemedicine.errors import NotFoundError, ValidationError

# The body of a request that records a consent. Everything except the notice
# version is optional.
NOTICE_VERSION = "notice_version"
METHOD = "method"
EVIDENCE = "evidence"

# The path segment that acknowledges the notice, rather than granting a
# consent for a purpose.
NOTICE = "notice"

# The path segment that withdraws a consent, for the clients that would
# rather ask for it with a POST than a DELETE.
WITHDRAW = "withdraw"


class ConsentEndpoints:
    """The consent endpoints, called by the FHIR application."""

    def __init__(self, consent: ConsentService):
        self.consent = consent

    # -- the entry point ---------------------------------------------------

    def handle(self, method: str, remainder: str, query: Optional[Dict],
               actor, body: bytes) -> Tuple[int, Optional[dict]]:
        """Handle one request. Returns the status and the payload."""
        tail = _tail(remainder)

        if method == "GET":
            return 200, self.read(actor, query or {})
        if method == "POST":
            return 201, self.write(actor, tail, body)
        if method == "DELETE":
            self.remove(actor, tail)
            return 204, None
        raise ValidationError(f"{method} is not supported on the consent endpoint")

    # -- the operations ----------------------------------------------------

    def read(self, actor, query: Dict) -> dict:
        """The consent state: the caller's own, or a patient's."""
        patient_id = _first(query, "patient")
        if patient_id:
            return self.consent.state_for_patient(actor, patient_id)
        return self.consent.state_for_actor(actor)

    def write(self, actor, tail: list, body: bytes) -> dict:
        """Acknowledge the notice, grant a consent, or withdraw one.

        A withdrawal may be asked for in two ways: ``DELETE
        /fhir/consent/<purpose>``, which is the plainest, and ``POST
        /fhir/consent/<purpose>/withdraw``, which some clients find easier
        to write. They do the same thing, and the section 35 requirement is
        the same either way: it must be as easy to withdraw as to give.
        """
        payload = _parse(body)
        if not tail:
            raise ValidationError("a purpose is required")
        if len(tail) == 2 and tail[1] == WITHDRAW:
            self.remove(actor, tail[:1])
            return self.consent.state_for_actor(actor)
        if len(tail) > 1:
            raise ValidationError("there is no such consent endpoint")

        if tail[0] == NOTICE:
            version = _required(payload, NOTICE_VERSION)
            return self.consent.acknowledge_for_actor(
                actor, version,
                method=_optional(payload, METHOD, "web"),
                evidence=_optional(payload, EVIDENCE, None))

        purpose = _known_purpose(tail[0])
        version = _required(payload, NOTICE_VERSION)
        return self.consent.grant_for_actor(
            actor, purpose, version,
            method=_optional(payload, METHOD, "web"),
            evidence=_optional(payload, EVIDENCE, None))

    def remove(self, actor, tail: list) -> None:
        """Withdraw a consent for one optional purpose."""
        if not tail:
            raise ValidationError("a purpose is required")
        if len(tail) > 1:
            raise ValidationError("there is no such consent endpoint")
        purpose = _known_purpose(tail[0])
        self.consent.withdraw_for_actor(actor, purpose)


# --------------------------------------------------------------------------
# The helpers
# --------------------------------------------------------------------------


def _tail(remainder: str) -> list:
    """The path below ``/fhir/consent``."""
    segments = [segment for segment in remainder.split("/") if segment]
    if segments and segments[0] == "consent":
        segments = segments[1:]
    return segments


def _first(query: Dict, name: str) -> Optional[str]:
    """One value of a query parameter."""
    value = query.get(name)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _parse(body: bytes) -> dict:
    if not body:
        return {}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"the body is not valid JSON: {error}") from None
    if not isinstance(payload, dict):
        raise ValidationError("the body must be a JSON object")
    return payload


def _required(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not value or not str(value).strip():
        raise ValidationError(
            f"'{name}' is required: a consent has to name the version of the "
            "notice the patient saw, so that the record can be shown to be "
            "informed")
    return str(value).strip()


def _optional(payload: dict, name: str, default):
    value = payload.get(name)
    if value is None:
        return default
    return str(value).strip()


def _known_purpose(purpose: str) -> str:
    if purpose not in OPTIONAL_PURPOSES:
        raise NotFoundError(
            f"'{purpose}' is not an optional purpose. The optional purposes "
            f"are: {', '.join(OPTIONAL_PURPOSES)}. The clinical record is not "
            "one of them: it is made under S.30(1)(g) of the NDPA, and the "
            "notice covers it")
    return purpose

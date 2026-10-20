"""Consent: what the patient has agreed to, and what they have withdrawn.

This is the machinery behind PRIV-02 of the compliance review, and it is
shaped by the Nigeria Data Protection Act 2023 rather than by the usual
"one form covering everything".

**The clinical record does not rest on consent.** Section 30(1)(g) of the
NDPA allows processing of sensitive personal data — and health status is
sensitive personal data — where it is "carried out for purposes of medical
care or community welfare, and undertaken by or under the responsibility of
a professional or similar service provider owing a duty of confidentiality".
A practice treating a patient is doing that. So the record of the
consultation is made under that ground, and the patient is told about it
rather than asked to sign for it.

**Consent is needed for everything else**, and Section 30(1)(a) requires it
to be given "for the specific purpose or purposes for which it will be
processed". So the optional uses — research, teaching, marketing, sharing
with a partner — each have their own consent, each can be withdrawn on its
own (Section 35), and bundling them into one blanket form would make the
optional uses unwithdrawable in practice, which is what the Act does not
allow.

**There are two different things here**, and they are kept apart on purpose:

* the **notice** — what the patient must be told before their data is
  collected (Section 27: the purposes, the recipients, the retention period,
  the rights, the right to complain to the Commission). Recording that the
  notice was shown is an *acknowledgement*, not a consent.
* the **consents** — one per optional purpose, each grantable and
  withdrawable, each tied to the version of the notice the patient saw.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog

# The optional uses that need a consent of their own. The clinical record is
# not one of them: it is made under S.30(1)(g) of the NDPA.
PURPOSE_RESEARCH = "research"
PURPOSE_TEACHING = "teaching"
PURPOSE_MARKETING = "marketing"
PURPOSE_PARTNER_SHARING = "partner_sharing"

OPTIONAL_PURPOSES: Tuple[str, ...] = (
    PURPOSE_RESEARCH,
    PURPOSE_TEACHING,
    PURPOSE_MARKETING,
    PURPOSE_PARTNER_SHARING,
)

PURPOSE_DESCRIPTIONS: Dict[str, str] = {
    PURPOSE_RESEARCH: (
        "Using your records, with the identifying details removed, for research into "
        "care and treatments."
    ),
    PURPOSE_TEACHING: (
        "Using your records, with the identifying details removed, to teach students "
        "and trainees."
    ),
    PURPOSE_MARKETING: (
        "Contacting you about the services this practice offers."
    ),
    PURPOSE_PARTNER_SHARING: (
        "Sharing your records with another practice or provider you have asked us to "
        "share them with."
    ),
}

# The events a record of consent can hold.
GRANTED = "granted"
WITHDRAWN = "withdrawn"
ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True)
class ConsentEvent:
    """One thing that happened, in the life of a consent.

    The record is append-only: a withdrawal is a new event, not a change to
    the old one, so that what the patient agreed to and when they stopped
    agreeing to it can both be shown.
    """

    event_id: str
    user_id: str
    kind: str                 # granted | withdrawn | acknowledged
    purpose: Optional[str]    # None for an acknowledgement of the notice
    notice_version: str
    occurred_at: datetime
    method: str = "web"       # how the patient gave it
    evidence: Optional[str] = None


class ConsentStore:
    """Where the consent events are kept."""

    def append(self, event: ConsentEvent) -> ConsentEvent:
        raise NotImplementedError

    def events_for(self, user_id: str) -> List[ConsentEvent]:
        raise NotImplementedError

    def events_for_purpose(self, user_id: str, purpose: str) -> List[ConsentEvent]:
        raise NotImplementedError


class InMemoryConsentStore(ConsentStore):
    """The consent events, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._events: List[ConsentEvent] = []

    def append(self, event: ConsentEvent) -> ConsentEvent:
        with self._lock:
            self._events.append(event)
        return event

    def events_for(self, user_id: str) -> List[ConsentEvent]:
        with self._lock:
            return [event for event in self._events if event.user_id == user_id]

    def events_for_purpose(self, user_id: str, purpose: str) -> List[ConsentEvent]:
        with self._lock:
            return [event for event in self._events
                    if event.user_id == user_id and event.purpose == purpose]


class ConsentService:
    """Grants, withdrawals, and the question "may we do this?"."""

    def __init__(self, store: Optional[ConsentStore] = None,
                 audit: Optional[AuditLog] = None, clock=None):
        self.store = store if store is not None else InMemoryConsentStore()
        self.audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- recording ---------------------------------------------------------

    def acknowledge_notice(self, user_id: str, notice_version: str,
                            method: str = "web",
                            evidence: Optional[str] = None) -> ConsentEvent:
        """Record that the patient was shown the notice.

        This is **not** a consent. It is the record that the Section 27
        notice was given, which is what the Act asks for, and it is kept
        apart from the consents so that the two are never confused.
        """
        event = self._event(user_id, ACKNOWLEDGED, None, notice_version, method, evidence)
        self.store.append(event)
        self._audit(user_id, "consent.notice_acknowledged", event, OUTCOME_SUCCESS)
        return event

    def grant(self, user_id: str, purpose: str, notice_version: str,
               method: str = "web", evidence: Optional[str] = None) -> ConsentEvent:
        """Record a consent for one optional purpose."""
        if purpose not in OPTIONAL_PURPOSES:
            raise ValueError(
                f"'{purpose}' is not an optional purpose. The clinical record does "
                "not need a consent: it is made under S.30(1)(g) of the NDPA, for "
                "the purposes of medical care and under the responsibility of a "
                "professional owing a duty of confidentiality, and the notice "
                "covers it.")
        event = self._event(user_id, GRANTED, purpose, notice_version, method, evidence)
        self.store.append(event)
        self._audit(user_id, "consent.granted", event, OUTCOME_SUCCESS)
        return event

    def withdraw(self, user_id: str, purpose: str,
                 method: str = "web", evidence: Optional[str] = None) -> ConsentEvent:
        """Withdraw a consent for one optional purpose.

        A withdrawal takes effect at once: the purpose stops being allowed
        even though the earlier grant is still in the record.
        """
        event = self._event(user_id, WITHDRAWN, purpose, "", method, evidence)
        self.store.append(event)
        self._audit(user_id, "consent.withdrawn", event, OUTCOME_SUCCESS)
        return event

    # -- asking ------------------------------------------------------------

    def has_consent(self, user_id: str, purpose: str) -> bool:
        """Whether the patient has agreed to this purpose, and not withdrawn it."""
        return self.current_state(user_id, purpose) == "granted"

    def current_state(self, user_id: str, purpose: str) -> Optional[str]:
        """The state of one purpose: ``granted``, ``withdrawn`` or nothing."""
        events = self.store.events_for_purpose(user_id, purpose)
        if not events:
            return None
        return events[-1].kind

    def granted_purposes(self, user_id: str) -> List[str]:
        """The optional purposes the patient has agreed to."""
        return [purpose for purpose in OPTIONAL_PURPOSES
                if self.has_consent(user_id, purpose)]

    def notice_acknowledged(self, user_id: str) -> bool:
        """Whether the patient has been shown the notice."""
        return any(event.kind == ACKNOWLEDGED
                   for event in self.store.events_for(user_id))

    def history(self, user_id: str) -> List[ConsentEvent]:
        """Everything that happened, in order."""
        return sorted(self.store.events_for(user_id), key=lambda event: event.occurred_at)

    # -- internals ---------------------------------------------------------

    def _event(self, user_id: str, kind: str, purpose: Optional[str],
              notice_version: str, method: str,
              evidence: Optional[str]) -> ConsentEvent:
        return ConsentEvent(
            event_id=str(uuid.uuid4()),
            user_id=user_id,
            kind=kind,
            purpose=purpose,
            notice_version=notice_version,
            occurred_at=self._clock(),
            method=method,
            evidence=evidence,
        )

    def _audit(self, user_id: str, action: str, event: ConsentEvent, outcome: str) -> None:
        if self.audit is None:
            return
        self.audit.append(
            actor_user_id=user_id,
            actor_role="patient",
            action=action,
            resource_type="consent",
            resource_id=event.event_id,
            outcome=outcome,
            detail=(f"{event.kind} for {event.purpose or 'the notice'} "
                    f"(notice version {event.notice_version or 'n/a'})"),
        )


def notice_digest(text: str) -> str:
    """The digest of a notice.

    A consent is tied to the version of the notice the patient saw, and
    this is the digest of that version, so that the record cannot be
    separated from the words the patient actually read.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

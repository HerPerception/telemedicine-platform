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
from telemedicine.authorization import (
    AccessScope,
    Action,
    Authorizer,
    ResourceType,
)
from telemedicine.errors import AuthorizationError, ValidationError

# The optional uses that need a consent of their own. The clinical record is
# not one of them: it is made under S.30(1)(g) of the NDPA.
PURPOSE_RESEARCH = "research"
PURPOSE_TEACHING = "teaching"
PURPOSE_MARKETING = "marketing"
PURPOSE_PARTNER_SHARING = "partner_sharing"
# Added by ENG-019: recording the consultation. It is an optional use like
# the others, and it needs its own consent, because the picture and the
# voice are health data.
PURPOSE_CONSULTATION_RECORDING = "consultation_recording"

OPTIONAL_PURPOSES: Tuple[str, ...] = (
    PURPOSE_RESEARCH,
    PURPOSE_TEACHING,
    PURPOSE_MARKETING,
    PURPOSE_PARTNER_SHARING,
    PURPOSE_CONSULTATION_RECORDING,
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
    PURPOSE_CONSULTATION_RECORDING: (
        "Recording the video consultation, so that it can be kept with your record and "
        "looked at again later."
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
    """Grants, withdrawals, and the question "may we do this?".

    The service answers two kinds of question:

    * **the patient's** — what have they agreed to, and what have they
      withdrawn? Only they may change it.
    * **the clinician's** — has this patient agreed to this purpose? They may
      read the state of a patient they treat, because they have to know
      before they use a record for a research purpose. They may not change
      it: consent is the patient's own act.
    """

    def __init__(self, store: Optional[ConsentStore] = None,
                 audit: Optional[AuditLog] = None, clock=None,
                 records=None, authorizer=None):
        self.store = store if store is not None else InMemoryConsentStore()
        self.audit = audit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # The clinical records, for the scope of a patient. It is optional:
        # without it the service cannot answer a clinician's question, and
        # says so rather than guessing.
        self.records = records
        self.authorizer = authorizer if authorizer is not None else Authorizer()

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
        self._audit_event(user_id, "consent.notice_acknowledged", event, OUTCOME_SUCCESS)
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
        self._audit_event(user_id, "consent.granted", event, OUTCOME_SUCCESS)
        return event

    def withdraw(self, user_id: str, purpose: str,
                 method: str = "web", evidence: Optional[str] = None) -> ConsentEvent:
        """Withdraw a consent for one optional purpose.

        A withdrawal takes effect at once: the purpose stops being allowed
        even though the earlier grant is still in the record.
        """
        event = self._event(user_id, WITHDRAWN, purpose, "", method, evidence)
        self.store.append(event)
        self._audit_event(user_id, "consent.withdrawn", event, OUTCOME_SUCCESS)
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

    # -- what an actor may do ----------------------------------------------

    def state_for_actor(self, actor) -> Dict:
        """The actor's own consent state.

        This is what a patient sees when they ask what they have agreed to.
        It is not a clinical read, so it is not an access to anyone's record
        beyond their own.
        """
        return self.state_for_user(actor.user_id)

    def state_for_user(self, user_id: str) -> Dict:
        """The consent state of one account."""
        events = self.history(user_id)
        acknowledgement = None
        for event in events:
            if event.kind == ACKNOWLEDGED:
                acknowledgement = event

        purposes = []
        for purpose in OPTIONAL_PURPOSES:
            state = self.current_state(user_id, purpose)
            last = self._last_event(events, purpose)
            purposes.append({
                "purpose": purpose,
                "description": PURPOSE_DESCRIPTIONS[purpose],
                # ``not_granted`` is the absence of a decision, which is
                # different from a decision not to agree.
                "state": state if state is not None else "not_granted",
                "notice_version": last.notice_version if last else None,
                "changed_at": _isoformat(last.occurred_at) if last else None,
            })

        return {
            "notice_acknowledged": acknowledgement is not None,
            "notice_version": acknowledgement.notice_version if acknowledgement else None,
            "notice_acknowledged_at": (
                _isoformat(acknowledgement.occurred_at) if acknowledgement else None),
            "purposes": purposes,
        }

    def state_for_patient(self, actor, patient_id: str) -> Dict:
        """The consent state of a patient, for a clinician who treats them.

        The patient is found through the clinical records, because that is
        where the treatment relationship — and so the access — comes from.
        """
        if self.records is None:
            raise ValidationError(
                "the consent service has no clinical records, so it cannot "
                "decide who may see a patient's consents")
        try:
            scope = self.records.patient_access_scope(patient_id)
        except ValidationError:
            # A patient id that is not there, and one the caller may not see,
            # have to look the same. Otherwise the endpoint is a way of
            # finding out which patients the practice has.
            self._audit(actor, "consent.viewed", patient_id, OUTCOME_DENIED,
                        f"read the consent state of patient {patient_id}")
            raise AuthorizationError(
                "not permitted", resource_type="consent", resource_id=patient_id,
                action="read")
        self._authorize(actor, Action.READ, ResourceType.CONSENT, scope,
                        patient_id, audit_action="consent.viewed",
                        detail=f"read the consent state of patient {patient_id}")
        state = self.state_for_user(scope.owner_user_id)
        return state

    def grant_for_actor(self, actor, purpose: str, notice_version: str,
                        method: str = "web", evidence: Optional[str] = None) -> Dict:
        """Record the actor's own consent for one optional purpose.

        Only a patient may do this. A clinician who could press the button
        on their behalf could take the consent away as well.
        """
        self._require_own_consent(actor)
        self.grant(actor.user_id, purpose, notice_version, method=method,
                   evidence=evidence)
        return self.state_for_user(actor.user_id)

    def withdraw_for_actor(self, actor, purpose: str, method: str = "web",
                           evidence: Optional[str] = None) -> Dict:
        """Withdraw the actor's own consent for one optional purpose."""
        self._require_own_consent(actor)
        self.withdraw(actor.user_id, purpose, method=method, evidence=evidence)
        return self.state_for_user(actor.user_id)

    def acknowledge_for_actor(self, actor, notice_version: str,
                              method: str = "web",
                              evidence: Optional[str] = None) -> Dict:
        """Record that the actor was shown the notice."""
        self._require_own_consent(actor)
        self.acknowledge_notice(actor.user_id, notice_version, method=method,
                                evidence=evidence)
        return self.state_for_user(actor.user_id)

    def may_use_for_purpose(self, user_id: str, purpose: str) -> bool:
        """Whether a record may be used for an optional purpose.

        This is the question a clinician asks before using a record for
        research, and it is asked about the patient's account, not about the
        clinician: the answer is the patient's decision, whoever is asking.
        """
        return self.has_consent(user_id, purpose)

    # -- internals ---------------------------------------------------------

    def _require_own_consent(self, actor) -> None:
        """Refuse unless the actor may change their own consents.

        The change itself is audited by the event it produces, so only a
        refusal is written here: two entries for one change would make the
        trail harder to read, not easier.
        """
        scope = AccessScope(owner_user_id=actor.user_id)
        self._authorize(actor, Action.UPDATE, ResourceType.CONSENT, scope,
                        actor.user_id, audit_action="consent.changed",
                        detail="change their own consents", audit_success=False)

    def _authorize(self, actor, action: Action, resource_type: ResourceType,
                   scope: AccessScope, resource_id: str, *, audit_action: str,
                   detail: str, audit_success: bool = True) -> None:
        """Authorize, audit the outcome, and raise if it was refused.

        The refusal is audited as well as the acceptance: a caller who was
        refused is exactly the thing an audit trail exists to show.
        """
        decision = self.authorizer.decide(actor, action, resource_type, scope)
        if decision.allowed:
            if audit_success:
                self._audit(actor, audit_action, resource_id, OUTCOME_SUCCESS, detail)
            return
        self._audit(actor, audit_action, resource_id, OUTCOME_DENIED, detail)
        raise AuthorizationError(
            decision.reason, resource_type=resource_type.value,
            resource_id=resource_id, action=action.value)

    @staticmethod
    def _last_event(events: List[ConsentEvent], purpose: str) -> Optional[ConsentEvent]:
        last = None
        for event in events:
            if event.purpose == purpose:
                last = event
        return last

    def _audit(self, actor, action: str, resource_id: str, outcome: str,
               detail: str) -> None:
        """One entry in the audit trail."""
        if self.audit is None:
            return
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=action,
            resource_type="consent",
            resource_id=resource_id,
            outcome=outcome,
            detail=detail,
        )

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

    def _audit_event(self, user_id: str, action: str, event: ConsentEvent,
                     outcome: str) -> None:
        """The entry for a consent event itself."""
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


def _isoformat(moment: datetime) -> str:
    """An instant as the API writes it: UTC, with a Z."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

"""Appointment booking and clinician schedule management.

This is the ENG-003 layer. It sits on top of the data model (ENG-001) and the
security layer (ENG-002):

* :class:`SlotService` manages a practitioner's bookable windows. A slot is
  authored in the practitioner's local wall-clock time and stored as a UTC
  instant, with the IANA zone kept alongside it.
* :class:`BookingService` books, reschedules and cancels appointments. Every
  call is authorized and audited, in the same way record access is.

The rules the MVP must honour, and where each is enforced:

``no double-booking``
    A slot can back at most one active appointment. The service checks it
    under a lock, ENG-001's schema enforces it with a unique index over the
    active appointments of a slot, and a second, overlapping slot for the
    same practitioner is rejected by a GiST exclusion constraint.

``reschedule/cancel frees a slot``
    Rescheduling moves the appointment to another slot, so the old one has no
    active appointment and is bookable again. Cancelling does the same, and
    keeps the cancelled appointment's reference to the slot it occupied, so
    the record of what was booked and released is not lost.

``time-zone correctness``
    Slots are authored in local time and stored in UTC. Local times that do
    not exist (a daylight-saving gap) or that occur twice (an overlap) are
    refused rather than silently shifted, and every comparison is made on the
    UTC instants.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.authorization import (
    OWN,
    TREATING,
    AccessScope,
    Action,
    Authorizer,
    ResourceType,
)
from telemedicine.errors import AuthorizationError, ConflictError, ValidationError
from telemedicine.models import Role, UserAccount
from telemedicine.notifications import (
    KIND_APPOINTMENT_BOOKED,
    KIND_APPOINTMENT_CANCELLED,
    KIND_APPOINTMENT_RESCHEDULED,
)
from telemedicine.records import Appointment, RecordsService
from telemedicine.repositories import InMemorySlotRepository, SlotRepository

# Mirrors of the constraints in db/schema.sql (ENG-001), so that the service
# refuses what the database would refuse.
MIN_SLOT_DURATION = timedelta(minutes=1)
MAX_SLOT_DURATION = timedelta(hours=12)

# Slot status values, as in the FHIR SlotStatus value set.
SLOT_FREE = "free"
SLOT_BUSY = "busy"

# Appointment status values, as in the FHIR AppointmentStatus value set.
APPOINTMENT_BOOKED = "booked"
APPOINTMENT_CANCELLED = "cancelled"

# Audit actions.
ACTION_SLOT_CREATE = "slot.create"
ACTION_SLOT_CLOSE = "slot.close"
ACTION_BOOK = "appointment.book"
ACTION_RESCHEDULE = "appointment.reschedule"
ACTION_CANCEL = "appointment.cancel"


class SlotTimeError(ValidationError):
    """A local wall-clock time could not be resolved to a single instant."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_local_time(local: datetime, timezone_name: str, *, fold: Optional[int] = None) -> datetime:
    """Resolve a local wall-clock time to a UTC instant.

    ``local`` is naive and is interpreted in ``timezone_name`` (an IANA zone
    name such as ``Europe/Berlin``).

    Two cases need a decision rather than a guess:

    * a **gap** — the local time does not exist, because the clocks jumped
      forward. The call is refused: booking a slot that never happened would
      put the appointment at the wrong time.
    * an **overlap** — the local time happens twice, because the clocks fell
      back. The call is refused unless the caller says which one it means
      with ``fold=0`` (the first) or ``fold=1`` (the second).
    """
    if not isinstance(local, datetime):
        raise SlotTimeError("a local time must be a datetime")
    if local.tzinfo is not None:
        raise SlotTimeError(
            "pass a naive local time; the zone is given by the timezone argument")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise SlotTimeError(f"unknown time zone '{timezone_name}'") from exc

    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset():
        round_trip = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
        if round_trip != local:
            raise SlotTimeError(
                f"{local.isoformat()} does not exist in {timezone_name} "
                "(the clocks jump forward at that time)")
        if fold is None:
            raise SlotTimeError(
                f"{local.isoformat()} happens twice in {timezone_name} "
                "(the clocks fall back at that time); pass fold=0 or fold=1")
        chosen = second if fold == 1 else first
    else:
        chosen = first
    return chosen.astimezone(timezone.utc)


def to_local_time(instant: datetime, timezone_name: str) -> datetime:
    """Render a UTC instant in a local zone, for display to a user."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise SlotTimeError(f"unknown time zone '{timezone_name}'") from exc
    if instant.tzinfo is None:
        raise SlotTimeError("an instant must be timezone-aware")
    return instant.astimezone(zone)


@dataclass(frozen=True)
class Slot:
    """A bookable window in a practitioner's schedule."""

    slot_id: str
    practitioner_id: str
    practitioner_user_id: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: str = SLOT_FREE

    @property
    def duration(self) -> timedelta:
        return self.ends_at - self.starts_at

    def contains(self, instant: datetime) -> bool:
        return self.starts_at <= instant < self.ends_at

    def overlaps(self, other: "Slot") -> bool:
        return self.starts_at < other.ends_at and other.starts_at < self.ends_at


class SlotService:
    """Creates and lists the bookable windows of a practitioner's schedule."""

    def __init__(self, audit: Optional[AuditLog] = None,
                 authorizer: Optional[Authorizer] = None,
                 repository: Optional[SlotRepository] = None,
                 clock=_utc_now):
        self.audit = audit if audit is not None else AuditLog(clock=clock)
        self.authorizer = authorizer if authorizer is not None else Authorizer()
        # Where the slots live. The default is the memory of one process; a
        # deployment passes the database one.
        self.repository: SlotRepository = (
            repository if repository is not None else InMemorySlotRepository())
        self._clock = clock
        self._lock = threading.Lock()

    # -- writing ----------------------------------------------------------

    def create_slot(self, actor: UserAccount, *, practitioner_id: str,
                    local_start: datetime, local_end: datetime, timezone_name: str,
                    fold: Optional[int] = None) -> Slot:
        """Open a slot in a practitioner's schedule.

        The window is given in the practitioner's local time and stored as a
        UTC instant. The slot may not overlap another slot of the same
        practitioner, which is the same rule the database's exclusion
        constraint enforces.
        """
        scope = AccessScope(owner_user_id=actor.user_id)
        self._require(actor, Action.CREATE, ResourceType.SLOT, scope, "slot",
                       "create a slot in their own schedule")

        starts_at = resolve_local_time(local_start, timezone_name, fold=fold)
        ends_at = resolve_local_time(local_end, timezone_name, fold=fold)
        if ends_at <= starts_at:
            raise ValidationError("a slot must end after it starts")
        if not MIN_SLOT_DURATION <= (ends_at - starts_at) <= MAX_SLOT_DURATION:
            raise ValidationError(
                f"a slot must be between {MIN_SLOT_DURATION} and {MAX_SLOT_DURATION} long")
        if starts_at.second or starts_at.microsecond or ends_at.second or ends_at.microsecond:
            raise ValidationError("slots start and end on whole minutes")

        with self._lock:
            clashes = [slot for slot in self.repository.list_slots()
                       if slot.practitioner_id == practitioner_id
                       and slot.status != "entered-in-error"
                       and slot.starts_at < ends_at and starts_at < slot.ends_at]
            if clashes:
                raise ValidationError(
                    "the slot overlaps an existing slot of this practitioner")

            slot = Slot(
                slot_id=str(uuid.uuid4()),
                practitioner_id=practitioner_id,
                practitioner_user_id=actor.user_id,
                starts_at=starts_at,
                ends_at=ends_at,
                timezone=timezone_name,
                status=SLOT_FREE,
            )
            self.repository.save_slot(slot)

        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_SLOT_CREATE,
            resource_type=ResourceType.SLOT.value,
            resource_id=slot.slot_id,
            outcome=OUTCOME_SUCCESS,
            detail=(f"opened slot {slot.starts_at.isoformat()} to {slot.ends_at.isoformat()} "
                    f"({timezone_name})"),
        )
        return slot

    def close_slot(self, actor: UserAccount, slot_id: str) -> Slot:
        """Close a slot that has no active appointment."""
        slot = self.get(slot_id)
        scope = AccessScope(owner_user_id=actor.user_id)
        self._require(actor, Action.UPDATE, ResourceType.SLOT, scope, "slot",
                       "close a slot in their own schedule")
        if slot.status == SLOT_BUSY:
            raise ValidationError("the slot is booked and must be cancelled, not closed")
        with self._lock:
            closed = replace(slot, status="entered-in-error")
            self.repository.save_slot(closed)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_SLOT_CLOSE,
            resource_type=ResourceType.SLOT.value,
            resource_id=slot.slot_id,
            outcome=OUTCOME_SUCCESS,
            detail="closed slot",
        )
        return closed

    # -- reading ----------------------------------------------------------

    def get(self, slot_id: str) -> Slot:
        slot = self.repository.get_slot(slot_id)
        if slot is None:
            raise ValidationError(f"no slot with id '{slot_id}'")
        return slot

    def list_slots(self, practitioner_id: str) -> List[Slot]:
        return self.repository.slots_for_practitioner(practitioner_id)

    def list_free_slots(self, practitioner_id: str, *, after: Optional[datetime] = None,
                        before: Optional[datetime] = None) -> List[Slot]:
        """The bookable slots of a practitioner, in start order.

        ``after`` and ``before`` are UTC instants; the comparison is made on
        the instants, never on the rendered local times.
        """
        slots = [slot for slot in self.list_slots(practitioner_id)
                 if slot.status == SLOT_FREE]
        if after is not None:
            slots = [slot for slot in slots if slot.ends_at > after]
        if before is not None:
            slots = [slot for slot in slots if slot.starts_at < before]
        return sorted(slots, key=lambda slot: slot.starts_at)

    def slot_for_local_time(self, practitioner_id: str, local: datetime,
                            timezone_name: str) -> Optional[Slot]:
        """The slot of a practitioner that covers a local wall-clock time."""
        instant = resolve_local_time(local, timezone_name)
        for slot in self.list_slots(practitioner_id):
            if slot.contains(instant):
                return slot
        return None

    def _set_status(self, slot_id: str, status: str) -> Slot:
        with self._lock:
            slot = self.repository.get_slot(slot_id)
            updated = replace(slot, status=status)
            return self.repository.save_slot(updated)

    def _require(self, actor: UserAccount, action: Action, resource_type: ResourceType,
                 scope: AccessScope, resource_id: str, detail: str) -> None:
        decision = self.authorizer.decide(actor, action, resource_type, scope)
        if decision.allowed:
            return
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=f"{resource_type.value}.{action.value}",
            resource_type=resource_type.value,
            resource_id=resource_id,
            outcome=OUTCOME_DENIED,
            detail=f"denied: {decision.reason}",
        )
        raise AuthorizationError(decision.reason, resource_type=resource_type.value,
                                 resource_id=resource_id, action=action.value)


class BookingService:
    """Books, reschedules and cancels appointments."""

    def __init__(self, slots: SlotService, authorizer: Optional[Authorizer] = None,
                 audit: Optional[AuditLog] = None, accounts=None, records=None,
                 notifications=None, clock=_utc_now):
        self.slots = slots
        self.authorizer = authorizer if authorizer is not None else Authorizer()
        self.audit = audit if audit is not None else AuditLog(clock=clock)
        # Optional: the account repository, used to find the clinical record id
        # of a patient account; and the records service, so that a booked
        # appointment is visible to the read paths of ENG-002.
        self.accounts = accounts
        # The appointments are the records of ENG-002, so the records service
        # is where they live. The booking service keeps no copy: the slot to
        # appointment mapping is a question about the data, and the data
        # answers it.
        self.records = records if records is not None else RecordsService(audit=self.audit)
        # Optional: where the confirmations are queued. Without it the booking
        # happens and nobody is told, which is what the MVP did until
        # ENG-011.
        self.notifications = notifications
        self._clock = clock
        self._lock = threading.Lock()

    # -- booking ----------------------------------------------------------

    def book(self, actor: UserAccount, slot_id: str,
             patient_user_id: Optional[str] = None) -> Appointment:
        """Book a slot.

        A patient books for themselves; a practitioner may book for a patient
        they treat. The slot must be free, in the future, and belong to the
        practitioner who is making the booking.
        """
        slot = self.slots.get(slot_id)
        patient_account, patient_id = self._resolve_patient(actor, patient_user_id)
        scope = AccessScope(
            owner_user_id=patient_account.user_id,
            treating_user_ids=frozenset({slot.practitioner_user_id}),
        )
        self._require(actor, Action.CREATE, ResourceType.APPOINTMENT, scope, slot_id,
                       "book an appointment", ACTION_BOOK,
                       f"book slot {slot_id}")

        now = self._clock()
        if slot.starts_at <= now:
            self._refuse(actor, ACTION_BOOK, ResourceType.APPOINTMENT.value, slot_id,
                         "the slot is in the past")
            raise ValidationError("the slot is in the past")

        with self._lock:
            existing = self.records.appointment_for_slot(slot.slot_id)
            if existing is not None and existing.status != APPOINTMENT_CANCELLED:
                self._refuse(actor, ACTION_BOOK, ResourceType.APPOINTMENT.value, slot_id,
                             "the slot is already booked")
                raise ConflictError("the slot is no longer available")
            appointment = Appointment(
                appointment_id=str(uuid.uuid4()),
                patient_id=patient_id,
                practitioner_id=slot.practitioner_id,
                patient_user_id=patient_account.user_id,
                practitioner_user_id=slot.practitioner_user_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                status=APPOINTMENT_BOOKED,
                slot_id=slot.slot_id,
            )
            self.records.add_appointment(appointment)

        self.slots._set_status(slot.slot_id, SLOT_BUSY)
        if self.records is not None:
            self.records.add_appointment(appointment)
        self._notify_appointment(KIND_APPOINTMENT_BOOKED, appointment)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_BOOK,
            resource_type=ResourceType.APPOINTMENT.value,
            resource_id=appointment.appointment_id,
            outcome=OUTCOME_SUCCESS,
            detail=(f"booked slot {slot.slot_id} "
                    f"({slot.starts_at.isoformat()} to {slot.ends_at.isoformat()})"),
        )
        return appointment

    # -- rescheduling and cancelling --------------------------------------

    def reschedule(self, actor: UserAccount, appointment_id: str,
                   new_slot_id: str) -> Appointment:
        """Move an appointment to another slot.

        The old slot is released, because no active appointment refers to it
        any more. The new slot must belong to the same practitioner and must
        be free and in the future.
        """
        appointment = self.get_appointment(appointment_id)
        new_slot = self.slots.get(new_slot_id)
        if new_slot.practitioner_id != appointment.practitioner_id:
            raise ValidationError(
                "the new slot belongs to a different practitioner; the MVP keeps "
                "appointments with the clinician who was booked")
        scope = AccessScope(
            owner_user_id=appointment.patient_user_id,
            treating_user_ids=frozenset({appointment.practitioner_user_id}),
        )
        self._require(actor, Action.UPDATE, ResourceType.APPOINTMENT, scope, appointment_id,
                       "reschedule an appointment", ACTION_RESCHEDULE,
                       f"reschedule appointment {appointment_id} to slot {new_slot_id}")

        now = self._clock()
        if new_slot.starts_at <= now:
            self._refuse(actor, ACTION_RESCHEDULE, ResourceType.APPOINTMENT.value,
                         appointment_id, "the new slot is in the past")
            raise ValidationError("the new slot is in the past")

        with self._lock:
            held = self.records.appointment_for_slot(new_slot.slot_id)
            if (held is not None and held.appointment_id != appointment_id
                    and held.status != APPOINTMENT_CANCELLED):
                self._refuse(actor, ACTION_RESCHEDULE, ResourceType.APPOINTMENT.value,
                             appointment_id, "the new slot is already booked")
                raise ConflictError("the new slot is no longer available")

            old_slot_id = appointment.slot_id
            moved = replace(
                appointment,
                starts_at=new_slot.starts_at,
                ends_at=new_slot.ends_at,
                slot_id=new_slot.slot_id,
            )
            self.records.add_appointment(moved)

        if old_slot_id is not None and old_slot_id != new_slot.slot_id:
            self.slots._set_status(old_slot_id, SLOT_FREE)
        self.slots._set_status(new_slot.slot_id, SLOT_BUSY)
        self._notify_appointment(KIND_APPOINTMENT_RESCHEDULED, moved)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_RESCHEDULE,
            resource_type=ResourceType.APPOINTMENT.value,
            resource_id=appointment_id,
            outcome=OUTCOME_SUCCESS,
            detail=(f"moved from slot {old_slot_id} to slot {new_slot.slot_id} "
                    f"({new_slot.starts_at.isoformat()})"),
        )
        return moved

    def cancel(self, actor: UserAccount, appointment_id: str,
               reason: str = "cancelled by the user") -> Appointment:
        """Cancel an appointment and release its slot.

        The appointment is kept, with its status changed to ``cancelled`` and
        a cancellation reason, so the record of what was booked and released
        survives. The slot becomes bookable again.
        """
        appointment = self.get_appointment(appointment_id)
        scope = AccessScope(
            owner_user_id=appointment.patient_user_id,
            treating_user_ids=frozenset({appointment.practitioner_user_id}),
        )
        self._require(actor, Action.UPDATE, ResourceType.APPOINTMENT, scope, appointment_id,
                       "cancel an appointment", ACTION_CANCEL,
                       f"cancel appointment {appointment_id}")
        if not reason:
            raise ValidationError("a cancellation needs a reason")

        with self._lock:
            cancelled = replace(appointment, status=APPOINTMENT_CANCELLED,
                                cancellation_reason=reason, cancelled_at=self._clock())
            self.records.add_appointment(cancelled)

        if appointment.slot_id is not None:
            self.slots._set_status(appointment.slot_id, SLOT_FREE)
        self._notify_appointment(KIND_APPOINTMENT_CANCELLED, cancelled)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_CANCEL,
            resource_type=ResourceType.APPOINTMENT.value,
            resource_id=appointment_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"cancelled: {reason}",
        )
        return cancelled

    # -- reading ----------------------------------------------------------

    def get_appointment(self, appointment_id: str) -> Appointment:
        appointment = self.records.get_appointment(appointment_id)
        if appointment is None:
            raise ValidationError(f"no appointment with id '{appointment_id}'")
        return appointment

    def list_appointments(self, *, patient_user_id: Optional[str] = None,
                          practitioner_id: Optional[str] = None) -> List[Appointment]:
        appointments = self.records.list_appointments()
        if patient_user_id is not None:
            appointments = [item for item in appointments
                            if item.patient_user_id == patient_user_id]
        if practitioner_id is not None:
            appointments = [item for item in appointments
                            if item.practitioner_id == practitioner_id]
        return sorted(appointments, key=lambda item: item.starts_at)

    def is_slot_booked(self, slot_id: str) -> bool:
        """Whether an active appointment occupies a slot."""
        appointment = self.records.appointment_for_slot(slot_id)
        return appointment is not None and appointment.status != APPOINTMENT_CANCELLED

    # -- internals --------------------------------------------------------

    def _resolve_patient(self, actor: UserAccount,
                         patient_user_id: Optional[str]) -> Tuple[UserAccount, str]:
        """Work out which patient the appointment is for, and their record id."""
        if actor.role == Role.PATIENT:
            if patient_user_id is not None and patient_user_id != actor.user_id:
                raise AuthorizationError(
                    "a patient may only book for themselves",
                    resource_type=ResourceType.APPOINTMENT.value,
                    action=Action.CREATE.value)
            if not actor.record_id:
                raise ValidationError("the patient account is not linked to a patient record")
            return actor, actor.record_id

        # A practitioner books for a patient they treat.
        if not patient_user_id:
            raise ValidationError("a practitioner booking must name the patient")
        if self.accounts is None:
            raise ValidationError("no account repository is available to resolve the patient")
        account = self.accounts.get_by_id(patient_user_id)
        if account is None:
            raise ValidationError(f"no account with id '{patient_user_id}'")
        if account.role != Role.PATIENT:
            raise ValidationError("appointments can only be booked for a patient account")
        if not account.record_id:
            raise ValidationError("the patient account is not linked to a patient record")
        return account, account.record_id

    def _notify_appointment(self, kind: str, appointment: Appointment) -> None:
        """Tell both parties that the appointment changed.

        The message is queued, not sent: the delivery is somebody else's job,
        and a crash between the booking and the sending must not lose the
        confirmation.
        """
        if self.notifications is None:
            return
        from telemedicine.notifications import (
            AUDIENCE_CLINICIAN,
            AUDIENCE_PATIENT,
            appointment_message,
        )
        for recipient, audience in ((appointment.patient_user_id, AUDIENCE_PATIENT),
                                    (appointment.practitioner_user_id, AUDIENCE_CLINICIAN)):
            if not recipient:
                continue
            subject, body = appointment_message(kind, appointment, audience)
            self.notifications.queue(kind=kind, recipient_user_id=recipient,
                                     subject=subject, body=body)

    def _require(self, actor: UserAccount, action: Action, resource_type: ResourceType,
                 scope: AccessScope, resource_id: str, what: str, audit_action: str,
                 detail: str) -> None:
        decision = self.authorizer.decide(actor, action, resource_type, scope)
        if decision.allowed:
            return
        self._refuse(actor, audit_action, resource_type.value, resource_id,
                     f"denied: {decision.reason}")
        raise AuthorizationError(decision.reason, resource_type=resource_type.value,
                                 resource_id=resource_id, action=action.value)

    def _refuse(self, actor: UserAccount, audit_action: str, resource_type: str,
                resource_id: str, detail: str) -> None:
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=audit_action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=OUTCOME_DENIED,
            detail=detail,
        )

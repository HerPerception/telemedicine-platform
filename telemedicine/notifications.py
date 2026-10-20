"""Notifications: what the practice tells people, and when.

A booking that nobody is told about has not happened as far as the patient is
concerned. The MVP has no mail server, so this module does the part that can
be done honestly and leaves the part that cannot:

* **the application queues the message**, in the same transaction as the thing
  that caused it, so that a crash between the booking and the sending cannot
  lose the confirmation;
* **something else sends it**, through the :class:`NotificationTransport`
  seam. The implementation here records what would be sent; a deployment
  supplies one that talks to a mail server.

The queue is durable: the rows are in the ``notification_outbox`` table of
``db/notification_schema.sql``, so a confirmation that was queued survives a
restart of the process that queued it.

The times in a message are in UTC. Rendering them in the recipient's own
zone is the client's business, and the message says which zone it is in.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional

from telemedicine.audit import OUTCOME_SUCCESS, AuditLog

# The kinds of message the MVP sends.
KIND_APPOINTMENT_BOOKED = "appointment.booked"
KIND_APPOINTMENT_RESCHEDULED = "appointment.rescheduled"
KIND_APPOINTMENT_CANCELLED = "appointment.cancelled"
KIND_PRESCRIPTION_ISSUED = "prescription.issued"

STATUS_QUEUED = "queued"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"

CHANNEL_EMAIL = "email"

# How many times a message is tried before it is given up on. A message that
# keeps failing — a wrong address, a full mailbox — must not be retried for
# ever, and somebody has to look at it.
MAX_ATTEMPTS = 5

# Audit actions.
ACTION_QUEUED = "notification.queued"
ACTION_SENT = "notification.sent"
ACTION_FAILED = "notification.failed"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Notification:
    """One message to send."""

    notification_id: str
    kind: str
    recipient_user_id: str
    subject: str
    body: str
    created_at: datetime
    channel: str = CHANNEL_EMAIL
    status: str = STATUS_QUEUED
    attempts: int = 0
    sent_at: Optional[datetime] = None
    last_error: Optional[str] = None

    @property
    def is_pending(self) -> bool:
        return self.status == STATUS_QUEUED


class NotificationStore:
    """Where the queued messages live."""

    def enqueue(self, notification: Notification) -> Notification:
        raise NotImplementedError

    def pending(self, limit: int = 100) -> List[Notification]:
        raise NotImplementedError

    def mark_sent(self, notification_id: str, when: datetime) -> None:
        raise NotImplementedError

    def mark_failed(self, notification_id: str, error: str, when: datetime) -> None:
        raise NotImplementedError

    def list_for_recipient(self, recipient_user_id: str) -> List[Notification]:
        raise NotImplementedError

    def get(self, notification_id: str) -> Optional[Notification]:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError


class InMemoryNotificationStore(NotificationStore):
    """The queued messages, in the memory of one process."""

    def __init__(self):
        self._lock = threading.Lock()
        self._notifications: Dict[str, Notification] = {}

    def enqueue(self, notification: Notification) -> Notification:
        with self._lock:
            self._notifications[notification.notification_id] = notification
        return notification

    def pending(self, limit: int = 100) -> List[Notification]:
        with self._lock:
            waiting = [item for item in self._notifications.values()
                       if item.status == STATUS_QUEUED]
        return sorted(waiting, key=lambda item: item.created_at)[:limit]

    def mark_sent(self, notification_id: str, when: datetime) -> None:
        with self._lock:
            item = self._notifications.get(notification_id)
            if item is not None:
                self._notifications[notification_id] = replace(
                    item, status=STATUS_SENT, sent_at=when, attempts=item.attempts + 1,
                    last_error=None)

    def mark_failed(self, notification_id: str, error: str, when: datetime) -> None:
        with self._lock:
            item = self._notifications.get(notification_id)
            if item is None:
                return
            attempts = item.attempts + 1
            self._notifications[notification_id] = replace(
                item,
                status=STATUS_FAILED if attempts >= MAX_ATTEMPTS else STATUS_QUEUED,
                attempts=attempts,
                last_error=error)

    def list_for_recipient(self, recipient_user_id: str) -> List[Notification]:
        with self._lock:
            return sorted(
                (item for item in self._notifications.values()
                 if item.recipient_user_id == recipient_user_id),
                key=lambda item: item.created_at)

    def get(self, notification_id: str) -> Optional[Notification]:
        with self._lock:
            return self._notifications.get(notification_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._notifications)


class NotificationTransport:
    """How a message leaves the system.

    The implementation here does not send anything: it records what would
    have been sent, which is what the tests read and what a demo shows. A
    deployment supplies an implementation that talks to a mail server.
    """

    def send(self, notification: Notification) -> None:
        """Send one message. Raise to say it could not be sent."""
        raise NotImplementedError


class RecordingTransport(NotificationTransport):
    """A transport that keeps what it was asked to send."""

    def __init__(self, fail_with: Optional[str] = None):
        self.sent: List[Notification] = []
        self.fail_with = fail_with

    def send(self, notification: Notification) -> None:
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        self.sent.append(notification)


# --------------------------------------------------------------------------
# The messages
# --------------------------------------------------------------------------


def format_instant(value: datetime) -> str:
    """A time, in UTC, in a form a person can read.

    The zone is spelled out, because the recipient is somewhere else.
    """
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d at %H:%M UTC")


# The two audiences. A patient and a clinician are told different things
# about the same appointment.
AUDIENCE_PATIENT = "patient"
AUDIENCE_CLINICIAN = "clinician"


def appointment_message(kind: str, appointment, audience: str) -> tuple:
    """The subject and the body of a message about an appointment.

    The text is deliberately plain: it is a notification, not a letter, and
    the client renders whatever it is sent. A deployment that sends HTML
    builds it at the transport, not here.
    """
    when = format_instant(appointment.starts_at)
    until = format_instant(appointment.ends_at)
    reference = appointment.appointment_id
    patient = audience == AUDIENCE_PATIENT

    if kind == KIND_APPOINTMENT_BOOKED:
        subject = "Your appointment is booked" if patient else "An appointment has been booked"
        opening = ("Your appointment is booked." if patient
                   else "An appointment has been booked for one of your patients.")
    elif kind == KIND_APPOINTMENT_RESCHEDULED:
        subject = ("Your appointment has been moved" if patient
                   else "An appointment has been moved")
        opening = ("Your appointment has been moved." if patient
                   else "An appointment of yours has been moved.")
    elif kind == KIND_APPOINTMENT_CANCELLED:
        subject = ("Your appointment has been cancelled" if patient
                   else "An appointment has been cancelled")
        opening = ("Your appointment has been cancelled." if patient
                   else "An appointment of yours has been cancelled.")
    else:
        subject = "About your appointment"
        opening = "There is news about an appointment."

    body = (f"{opening}\n\n"
            f"When: {when} until {until}\n"
            f"Reference: {reference}\n")
    return subject, body


def prescription_message(prescription, audience: str) -> tuple:
    """The subject and the body of the message about a prescription."""
    patient = audience == AUDIENCE_PATIENT
    subject = "Your prescription is ready" if patient else "A prescription has been issued"
    opening = ("Your prescription is ready." if patient
               else "You have issued a prescription.")
    body = (f"{opening}\n\n"
            f"Medication: {prescription.medication_display}\n"
            f"Directions: {prescription.dosage_text}\n"
            f"Reference: {prescription.prescription_id}\n")
    return subject, body


@dataclass
class DeliveryReport:
    """What one pass of the delivery process did."""

    sent: int = 0
    failed: int = 0
    remaining: int = 0

    @property
    def total(self) -> int:
        return self.sent + self.failed


class NotificationService:
    """Queues the messages, and sends them when a transport is available."""

    def __init__(self, store: Optional[NotificationStore] = None,
                 transport: Optional[NotificationTransport] = None,
                 audit: Optional[AuditLog] = None, clock=_utc_now):
        self.store = store if store is not None else InMemoryNotificationStore()
        self.transport = transport
        self.audit = audit
        self._clock = clock

    # -- queueing ---------------------------------------------------------

    def queue(self, *, kind: str, recipient_user_id: str, subject: str, body: str,
              channel: str = CHANNEL_EMAIL) -> Notification:
        """Queue a message for a recipient."""
        notification = Notification(
            notification_id=str(uuid.uuid4()),
            kind=kind,
            recipient_user_id=recipient_user_id,
            subject=subject,
            body=body,
            created_at=self._clock(),
            channel=channel,
        )
        self.store.enqueue(notification)
        if self.audit is not None:
            self.audit.append(
                actor_user_id=None,
                actor_role="system",
                action=ACTION_QUEUED,
                resource_type="notification",
                resource_id=notification.notification_id,
                outcome=OUTCOME_SUCCESS,
                detail=f"queued '{kind}' for {recipient_user_id}",
            )
        return notification

    # -- delivering --------------------------------------------------------

    def deliver(self, limit: int = 100) -> DeliveryReport:
        """Send what is queued, through the transport.

        A message that cannot be sent is left queued with the error recorded,
        so that the next pass tries again — until it has been tried
        ``MAX_ATTEMPTS`` times, when it is given up on and somebody has to
        look at it.
        """
        report = DeliveryReport()
        if self.transport is None:
            report.remaining = len(self.store.pending(limit))
            return report
        for notification in self.store.pending(limit):
            try:
                self.transport.send(notification)
            except Exception as error:
                self.store.mark_failed(notification.notification_id, str(error), self._clock())
                report.failed += 1
                if self.audit is not None:
                    self.audit.append(
                        actor_user_id=None,
                        actor_role="system",
                        action=ACTION_FAILED,
                        resource_type="notification",
                        resource_id=notification.notification_id,
                        outcome=OUTCOME_SUCCESS,
                        detail=f"could not send '{notification.kind}': {error}",
                    )
                continue
            self.store.mark_sent(notification.notification_id, self._clock())
            report.sent += 1
            if self.audit is not None:
                self.audit.append(
                    actor_user_id=None,
                    actor_role="system",
                    action=ACTION_SENT,
                    resource_type="notification",
                    resource_id=notification.notification_id,
                    outcome=OUTCOME_SUCCESS,
                    detail=f"sent '{notification.kind}'",
                )
        report.remaining = len(self.store.pending(limit))
        return report

    # -- reading -----------------------------------------------------------

    def for_recipient(self, recipient_user_id: str) -> List[Notification]:
        """Everything that was queued for a recipient."""
        return self.store.list_for_recipient(recipient_user_id)

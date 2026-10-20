"""Tests for the notifications: the outbox, the delivery and the retry.

The tests that need a database are skipped without one.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)
        return self.now


class OutboxTest(unittest.TestCase):
    """The queue itself, in memory."""

    def setUp(self):
        from telemedicine.notifications import (
            InMemoryNotificationStore,
            NotificationService,
            RecordingTransport,
        )
        self.clock = FakeClock()
        self.store = InMemoryNotificationStore()
        self.transport = RecordingTransport()
        self.service = NotificationService(store=self.store, transport=self.transport,
                                          clock=self.clock)

    def test_a_queued_message_is_pending(self):
        notification = self.service.queue(
            kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
            subject="Your appointment is booked", body="When: ...")
        self.assertTrue(notification.is_pending)
        self.assertEqual(len(self.store.pending()), 1)

    def test_delivering_sends_and_marks_sent(self):
        self.service.queue(kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
                           subject="s", body="b")
        report = self.service.deliver()
        self.assertEqual(report.sent, 1)
        self.assertEqual(report.failed, 0)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.store.pending(), [])

    def test_a_message_that_cannot_be_sent_is_tried_again(self):
        from telemedicine.notifications import (
            InMemoryNotificationStore,
            NotificationService,
            RecordingTransport,
        )
        transport = RecordingTransport(fail_with="the mail server said no")
        service = NotificationService(store=InMemoryNotificationStore(), transport=transport,
                                     clock=self.clock)
        service.queue(kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
                      subject="s", body="b")

        report = service.deliver()
        self.assertEqual(report.failed, 1)
        self.assertEqual(report.sent, 0)
        # It is still queued, with the error recorded.
        pending = service.store.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].attempts, 1)
        self.assertIn("the mail server said no", pending[0].last_error)

    def test_a_message_is_given_up_on_after_too_many_attempts(self):
        from telemedicine.notifications import (
            MAX_ATTEMPTS,
            InMemoryNotificationStore,
            NotificationService,
            RecordingTransport,
        )
        transport = RecordingTransport(fail_with="no")
        service = NotificationService(store=InMemoryNotificationStore(), transport=transport,
                                     clock=self.clock)
        recipient = str(uuid.uuid4())
        service.queue(kind="appointment.booked", recipient_user_id=recipient,
                      subject="s", body="b")
        for _ in range(MAX_ATTEMPTS):
            service.deliver()
        # It is no longer queued: somebody has to look at it.
        self.assertEqual(service.store.pending(), [])
        message = service.store.list_for_recipient(recipient)[0]
        self.assertEqual(message.status, "failed")
        self.assertEqual(message.attempts, MAX_ATTEMPTS)

    def test_the_recipient_sees_what_was_queued_for_them(self):
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        self.service.queue(kind="appointment.booked", recipient_user_id=first,
                           subject="s", body="b")
        self.service.queue(kind="appointment.booked", recipient_user_id=second,
                           subject="s", body="b")
        mine = self.service.for_recipient(first)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0].recipient_user_id, first)

    def test_without_a_transport_nothing_is_sent(self):
        from telemedicine.notifications import (
            InMemoryNotificationStore,
            NotificationService,
        )
        service = NotificationService(store=InMemoryNotificationStore(), clock=self.clock)
        service.queue(kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
                      subject="s", body="b")
        report = service.deliver()
        self.assertEqual(report.sent, 0)
        self.assertEqual(report.remaining, 1)


class MessageTest(unittest.TestCase):
    def test_the_patient_and_the_clinician_are_told_different_things(self):
        from telemedicine.notifications import (
            AUDIENCE_CLINICIAN,
            AUDIENCE_PATIENT,
            KIND_APPOINTMENT_BOOKED,
            appointment_message,
        )
        from telemedicine.records import Appointment

        appointment = Appointment(
            appointment_id="appointment-1", patient_id="patient-1",
            practitioner_id="practitioner-1", patient_user_id="user-patient",
            practitioner_user_id="user-practitioner",
            starts_at=NOW, ends_at=NOW + timedelta(minutes=30), status="booked")

        patient_subject, patient_body = appointment_message(
            KIND_APPOINTMENT_BOOKED, appointment, AUDIENCE_PATIENT)
        clinician_subject, clinician_body = appointment_message(
            KIND_APPOINTMENT_BOOKED, appointment, AUDIENCE_CLINICIAN)

        self.assertIn("Your appointment", patient_subject)
        self.assertIn("Your appointment", patient_body)
        self.assertIn("An appointment", clinician_subject)
        self.assertIn("one of your patients", clinician_body)
        # Both say when, and which one.
        for body in (patient_body, clinician_body):
            self.assertIn("2026-10-21 at 12:00 UTC", body)
            self.assertIn("appointment-1", body)

    def test_the_time_is_spelled_out_in_utc(self):
        from telemedicine.notifications import format_instant
        self.assertEqual(format_instant(NOW), "2026-10-21 at 12:00 UTC")

    def test_a_cancellation_says_what_was_cancelled(self):
        from telemedicine.notifications import (
            AUDIENCE_PATIENT,
            KIND_APPOINTMENT_CANCELLED,
            appointment_message,
        )
        from telemedicine.records import Appointment

        appointment = Appointment(
            appointment_id="appointment-1", patient_id="patient-1",
            practitioner_id="practitioner-1", patient_user_id="user-patient",
            practitioner_user_id="user-practitioner",
            starts_at=NOW, ends_at=NOW + timedelta(minutes=30), status="cancelled")
        subject, body = appointment_message(KIND_APPOINTMENT_CANCELLED, appointment,
                                            AUDIENCE_PATIENT)
        self.assertIn("cancelled", subject)
        self.assertIn("2026-10-21 at 12:00 UTC", body)


class BookingNotificationTest(unittest.TestCase):
    """A booking tells both parties."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService, SlotService
        from telemedicine.models import Role
        from telemedicine.notifications import (
            InMemoryNotificationStore,
            NotificationService,
            RecordingTransport,
        )
        from telemedicine.records import RecordsService

        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.notifications = NotificationService(
            store=InMemoryNotificationStore(), transport=RecordingTransport())
        self.booking = BookingService(self.slots, records=self.records, audit=self.audit,
                                      accounts=self.auth.users,
                                      notifications=self.notifications)

        self.patient = self.auth.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                                          record_id="patient-1")
        self.practitioner = self.auth.register("dr@example.org", "a-long-passphrase",
                                               Role.PRACTITIONER, record_id="practitioner-1")

    def slot(self, hour=14):
        from datetime import datetime as dt
        return self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=dt(2026, 10, 21, hour, 0),
            local_end=dt(2026, 10, 21, hour, 30), timezone_name="Europe/Berlin")

    def test_a_booking_queues_a_confirmation_for_both_parties(self):
        from telemedicine.notifications import KIND_APPOINTMENT_BOOKED

        slot = self.slot()
        self.booking.book(self.patient, slot.slot_id)

        queued = self.notifications.store.list_for_recipient(self.patient.user_id)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].kind, KIND_APPOINTMENT_BOOKED)
        self.assertIn("Your appointment", queued[0].subject)

        queued = self.notifications.store.list_for_recipient(self.practitioner.user_id)
        self.assertEqual(len(queued), 1)
        self.assertIn("An appointment", queued[0].subject)

    def test_a_cancellation_queues_a_message_for_both_parties(self):
        from telemedicine.notifications import KIND_APPOINTMENT_CANCELLED

        slot = self.slot()
        appointment = self.booking.book(self.patient, slot.slot_id)
        self.booking.cancel(self.patient, appointment.appointment_id, reason="cannot make it")

        for account in (self.patient, self.practitioner):
            queued = self.notifications.store.list_for_recipient(account.user_id)
            self.assertEqual(len(queued), 2)
            self.assertEqual(queued[1].kind, KIND_APPOINTMENT_CANCELLED)

    def test_a_reschedule_queues_a_message(self):
        from telemedicine.notifications import KIND_APPOINTMENT_RESCHEDULED

        first = self.slot(14)
        second = self.slot(16)
        appointment = self.booking.book(self.patient, first.slot_id)
        self.booking.reschedule(self.patient, appointment.appointment_id, second.slot_id)

        queued = self.notifications.store.list_for_recipient(self.patient.user_id)
        self.assertEqual([item.kind for item in queued],
                         ["appointment.booked", "appointment.rescheduled"])

    def test_the_queue_is_drained_by_the_delivery_process(self):
        slot = self.slot()
        self.booking.book(self.patient, slot.slot_id)
        report = self.notifications.deliver()
        self.assertEqual(report.sent, 2)


class DurableOutboxTest(unittest.TestCase):
    """The queue survives a restart, because it is in the database."""

    def setUp(self):
        self.database = _fresh_database("telemedicine_notifications_test")
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")

    def test_a_queued_message_survives_a_restart(self):
        from telemedicine.notifications import NotificationService
        from telemedicine.persistence.notification_store import PostgresNotificationStore

        store = PostgresNotificationStore(self.database)
        service = NotificationService(store=store)
        queued = service.queue(kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
                               subject="s", body="b")

        # A new service over the same database: the message is still there.
        reopened = NotificationService(store=PostgresNotificationStore(self.database))
        pending = reopened.store.pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].notification_id, queued.notification_id)

    def test_a_delivered_message_is_marked_sent_in_the_database(self):
        from telemedicine.notifications import (
            NotificationService,
            RecordingTransport,
        )
        from telemedicine.persistence.notification_store import PostgresNotificationStore

        store = PostgresNotificationStore(self.database)
        service = NotificationService(store=store, transport=RecordingTransport())
        queued = service.queue(kind="appointment.booked", recipient_user_id=str(uuid.uuid4()),
                               subject="s", body="b")
        service.deliver()

        stored = PostgresNotificationStore(self.database).get(queued.notification_id)
        self.assertEqual(stored.status, "sent")
        self.assertIsNotNone(stored.sent_at)
        self.assertEqual(stored.attempts, 1)


if __name__ == "__main__":
    unittest.main()

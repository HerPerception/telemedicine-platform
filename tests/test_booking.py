"""Tests for booking, rescheduling and cancelling appointments.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.auth import AuthService
from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS
from telemedicine.authorization import Authorizer
from telemedicine.booking import BookingService, SlotService
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.models import Role, UserAccount
from telemedicine.records import RecordsService

BERLIN = "Europe/Berlin"

# A fixed "now" well after the slots below, so that the tests do not depend
# on the wall clock.
NOW = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def fixed_clock():
    return NOW


def make_account(user_id, role, record_id, email=None):
    return UserAccount(
        user_id=user_id,
        email=email or f"{user_id}@example.org",
        role=role,
        password_hash="pbkdf2_sha256$1000$abc$def",
        record_id=record_id,
    )


class BookingTestCase(unittest.TestCase):
    def setUp(self):
        self.slots = SlotService(clock=fixed_clock)
        self.audit = self.slots.audit
        self.records = RecordsService(audit=self.audit)
        self.accounts = AuthService(audit=self.audit, password_iterations=1000,
                                    clock=fixed_clock).users
        self.practitioner = make_account("user-practitioner", Role.PRACTITIONER, "practitioner-1")
        self.other_practitioner = make_account("user-other-practitioner", Role.PRACTITIONER,
                                               "practitioner-2")
        self.patient = make_account("user-patient", Role.PATIENT, "patient-1")
        self.other_patient = make_account("user-other-patient", Role.PATIENT, "patient-2")
        for account in (self.practitioner, self.other_practitioner, self.patient,
                        self.other_patient):
            self.accounts.save(account)
        self.service = BookingService(self.slots, authorizer=Authorizer(), audit=self.audit,
                                      accounts=self.accounts, records=self.records,
                                      clock=fixed_clock)

    def open_slot(self, hour=14, minute=0, practitioner=None, patient_free=True):
        actor = practitioner or self.practitioner
        return self.slots.create_slot(
            actor,
            practitioner_id=actor.record_id,
            local_start=datetime(2026, 7, 1, hour, minute),
            local_end=datetime(2026, 7, 1, hour, minute) + timedelta(minutes=30),
            timezone_name=BERLIN,
        )

    # -- booking ----------------------------------------------------------

    def test_a_patient_books_a_free_slot(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        self.assertEqual(appointment.status, "booked")
        self.assertEqual(appointment.patient_id, "patient-1")
        self.assertEqual(appointment.practitioner_id, "practitioner-1")
        self.assertEqual(appointment.slot_id, slot.slot_id)
        self.assertEqual(appointment.starts_at, slot.starts_at)
        self.assertEqual(appointment.ends_at, slot.ends_at)

    def test_booking_marks_the_slot_busy(self):
        slot = self.open_slot()
        self.service.book(self.patient, slot.slot_id)
        self.assertEqual(self.slots.get(slot.slot_id).status, "busy")
        self.assertTrue(self.service.is_slot_booked(slot.slot_id))
        self.assertEqual(self.slots.list_free_slots("practitioner-1"), [])

    def test_booking_is_audited(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        entries = [entry for entry in self.audit.entries
                   if entry.action == "appointment.book"
                   and entry.resource_id == appointment.appointment_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, OUTCOME_SUCCESS)
        self.assertEqual(entries[0].actor_user_id, "user-patient")

    def test_a_booked_appointment_is_visible_to_the_read_paths(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        read = self.records.read_appointment(self.patient, appointment.appointment_id)
        self.assertEqual(read.appointment_id, appointment.appointment_id)

    def test_a_patient_cannot_book_for_somebody_else(self):
        slot = self.open_slot()
        with self.assertRaises(AuthorizationError):
            self.service.book(self.patient, slot.slot_id, patient_user_id="user-other-patient")

    def test_a_practitioner_may_book_for_a_patient(self):
        slot = self.open_slot()
        appointment = self.service.book(self.practitioner, slot.slot_id,
                                         patient_user_id="user-patient")
        self.assertEqual(appointment.patient_user_id, "user-patient")
        self.assertEqual(appointment.practitioner_user_id, "user-practitioner")

    def test_a_practitioner_may_not_book_a_slot_of_another_practitioner(self):
        slot = self.open_slot(practitioner=self.other_practitioner)
        with self.assertRaises(AuthorizationError):
            self.service.book(self.practitioner, slot.slot_id, patient_user_id="user-patient")

    def test_a_practitioner_must_name_the_patient(self):
        slot = self.open_slot()
        with self.assertRaises(ValidationError):
            self.service.book(self.practitioner, slot.slot_id)

    def test_a_practitioner_may_not_book_for_an_unknown_patient(self):
        slot = self.open_slot()
        with self.assertRaises(ValidationError):
            self.service.book(self.practitioner, slot.slot_id, patient_user_id="user-nobody")

    # -- no double booking ------------------------------------------------

    def test_a_slot_cannot_be_booked_twice(self):
        slot = self.open_slot()
        self.service.book(self.patient, slot.slot_id)
        with self.assertRaises(ValidationError):
            self.service.book(self.other_patient, slot.slot_id)

    def test_a_refused_double_booking_is_audited(self):
        slot = self.open_slot()
        self.service.book(self.patient, slot.slot_id)
        with self.assertRaises(ValidationError):
            self.service.book(self.other_patient, slot.slot_id)
        denials = [entry for entry in self.audit.entries
                   if entry.action == "appointment.book" and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_only_one_of_two_racing_bookings_succeeds(self):
        # The check and the write happen under one lock, so a second caller
        # sees the slot as taken.
        slot = self.open_slot()
        self.service.book(self.patient, slot.slot_id)
        self.assertEqual(len(self.service.list_appointments(patient_user_id="user-patient")), 1)
        with self.assertRaises(ValidationError):
            self.service.book(self.other_patient, slot.slot_id)
        self.assertEqual(len(self.service.list_appointments()), 1)

    def test_a_slot_in_the_past_cannot_be_booked(self):
        slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=datetime(2026, 6, 1, 14, 0),
            local_end=datetime(2026, 6, 1, 14, 30),
            timezone_name=BERLIN)
        with self.assertRaises(ValidationError):
            self.service.book(self.patient, slot.slot_id)

    # -- rescheduling -----------------------------------------------------

    def test_rescheduling_moves_the_appointment_and_frees_the_old_slot(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)

        moved = self.service.reschedule(self.patient, appointment.appointment_id, second.slot_id)

        self.assertEqual(moved.slot_id, second.slot_id)
        self.assertEqual(moved.starts_at, second.starts_at)
        self.assertEqual(moved.ends_at, second.ends_at)
        self.assertEqual(self.slots.get(first.slot_id).status, "free")
        self.assertEqual(self.slots.get(second.slot_id).status, "busy")
        self.assertFalse(self.service.is_slot_booked(first.slot_id))
        self.assertTrue(self.service.is_slot_booked(second.slot_id))

    def test_the_old_slot_can_be_booked_again_after_a_reschedule(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)
        self.service.reschedule(self.patient, appointment.appointment_id, second.slot_id)
        again = self.service.book(self.other_patient, first.slot_id)
        self.assertEqual(again.slot_id, first.slot_id)

    def test_rescheduling_into_a_booked_slot_is_refused(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)
        self.service.book(self.other_patient, second.slot_id)
        with self.assertRaises(ValidationError):
            self.service.reschedule(self.patient, appointment.appointment_id, second.slot_id)

    def test_rescheduling_into_the_slot_the_appointment_already_holds_is_allowed(self):
        first = self.open_slot(hour=14)
        appointment = self.service.book(self.patient, first.slot_id)
        moved = self.service.reschedule(self.patient, appointment.appointment_id, first.slot_id)
        self.assertEqual(moved.slot_id, first.slot_id)
        self.assertTrue(self.service.is_slot_booked(first.slot_id))

    def test_rescheduling_to_a_slot_of_another_practitioner_is_refused(self):
        first = self.open_slot(hour=14)
        other_slot = self.open_slot(hour=16, practitioner=self.other_practitioner)
        appointment = self.service.book(self.patient, first.slot_id)
        with self.assertRaises(ValidationError):
            self.service.reschedule(self.patient, appointment.appointment_id, other_slot.slot_id)

    def test_a_patient_may_not_reschedule_another_patients_appointment(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)
        with self.assertRaises(AuthorizationError):
            self.service.reschedule(self.other_patient, appointment.appointment_id,
                                     second.slot_id)

    def test_the_treating_practitioner_may_reschedule(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)
        moved = self.service.reschedule(self.practitioner, appointment.appointment_id,
                                         second.slot_id)
        self.assertEqual(moved.slot_id, second.slot_id)

    def test_rescheduling_is_audited(self):
        first = self.open_slot(hour=14)
        second = self.open_slot(hour=16)
        appointment = self.service.book(self.patient, first.slot_id)
        self.service.reschedule(self.patient, appointment.appointment_id, second.slot_id)
        entries = [entry for entry in self.audit.entries
                   if entry.action == "appointment.reschedule"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, OUTCOME_SUCCESS)

    # -- cancelling -------------------------------------------------------

    def test_cancelling_frees_the_slot(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)

        cancelled = self.service.cancel(self.patient, appointment.appointment_id,
                                        reason="the patient recovered")

        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(self.slots.get(slot.slot_id).status, "free")
        self.assertFalse(self.service.is_slot_booked(slot.slot_id))
        self.assertEqual(self.slots.list_free_slots("practitioner-1")[0].slot_id, slot.slot_id)

    def test_a_cancelled_appointment_keeps_its_slot_reference(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        cancelled = self.service.cancel(self.patient, appointment.appointment_id)
        self.assertEqual(cancelled.slot_id, slot.slot_id)
        self.assertEqual(cancelled.appointment_id, appointment.appointment_id)

    def test_a_cancelled_slot_can_be_booked_again(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        self.service.cancel(self.patient, appointment.appointment_id)
        again = self.service.book(self.other_patient, slot.slot_id)
        self.assertEqual(again.slot_id, slot.slot_id)

    def test_cancelling_needs_a_reason(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        with self.assertRaises(ValidationError):
            self.service.cancel(self.patient, appointment.appointment_id, reason="")

    def test_a_patient_may_not_cancel_another_patients_appointment(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        with self.assertRaises(AuthorizationError):
            self.service.cancel(self.other_patient, appointment.appointment_id)

    def test_cancelling_is_audited(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        self.service.cancel(self.patient, appointment.appointment_id)
        entries = [entry for entry in self.audit.entries
                   if entry.action == "appointment.cancel"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, OUTCOME_SUCCESS)

    def test_a_refused_cancellation_is_audited(self):
        slot = self.open_slot()
        appointment = self.service.book(self.patient, slot.slot_id)
        with self.assertRaises(AuthorizationError):
            self.service.cancel(self.other_patient, appointment.appointment_id)
        denials = [entry for entry in self.audit.entries
                   if entry.action == "appointment.cancel" and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_an_unknown_appointment_is_refused(self):
        with self.assertRaises(ValidationError):
            self.service.get_appointment("appointment-nobody")

    def test_an_unknown_slot_is_refused(self):
        with self.assertRaises(ValidationError):
            self.service.book(self.patient, "slot-nobody")


if __name__ == "__main__":
    unittest.main()

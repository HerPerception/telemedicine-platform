"""Tests for the video consultation rooms.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.models import Role
from telemedicine.records import PatientRecord, PractitionerRecord, RecordsService
from telemedicine.video import (
    PARTICIPANT_ADMITTED,
    PARTICIPANT_WAITING,
    ROOM_CLOSED,
    ROOM_OPEN,
    JoinUnavailable,
    VideoService,
)

# Five minutes before the appointment, in UTC. The slot below is 14:00 in
# Berlin, which is 12:00 UTC in October, so the room opens at 11:45 UTC and
# closes at 12:40 UTC.
NOW = datetime(2026, 10, 21, 11, 55, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)
        return self.now


class VideoTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.audit = AuditLog(clock=self.clock)
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit, clock=self.clock)
        self.booking = BookingService(self.slots, audit=self.audit, records=self.records,
                                      clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000, clock=self.clock)

        self.patient = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.practitioner = self.auth.register("dr@example.org", "a-long-passphrase",
                                               Role.PRACTITIONER, record_id="practitioner-1")
        self.stranger = self.auth.register("nobody@example.org", "a-long-passphrase",
                                           Role.PATIENT, record_id="patient-2")
        self.other_clinician = self.auth.register("other-dr@example.org", "a-long-passphrase",
                                                   Role.PRACTITIONER, record_id="practitioner-2")

        self.records.add_patient(PatientRecord(patient_id="patient-1",
                                               user_id=self.patient.user_id,
                                               display_name="Ada Nwosu Okonkwo"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id=self.practitioner.user_id,
            display_name="Dr. Elena Ramirez"))

        self.slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 21, 14, 0), local_end=datetime(2026, 10, 21, 14, 30),
            timezone_name="Europe/Berlin")
        self.appointment = self.booking.book(self.patient, self.slot.slot_id)

        self.service = VideoService(self.records, audit=self.audit, clock=self.clock)

    def open_room(self):
        return self.service.open_room(self.practitioner, self.appointment.appointment_id)


class RoomOpeningTest(VideoTestCase):
    def test_the_clinician_opens_the_room(self):
        room = self.open_room()
        self.assertEqual(room.appointment_id, self.appointment.appointment_id)
        self.assertEqual(room.starts_at, self.appointment.starts_at)
        self.assertEqual(room.ends_at, self.appointment.ends_at)
        self.assertEqual(room.patient_user_id, self.patient.user_id)
        self.assertEqual(room.practitioner_user_id, self.practitioner.user_id)

    def test_a_patient_cannot_open_the_room(self):
        with self.assertRaises(AuthorizationError):
            self.service.open_room(self.patient, self.appointment.appointment_id)

    def test_a_clinician_who_is_not_delivering_cannot_open_the_room(self):
        with self.assertRaises(AuthorizationError):
            self.service.open_room(self.other_clinician, self.appointment.appointment_id)

    def test_opening_the_same_room_twice_returns_the_same_room(self):
        first = self.open_room()
        second = self.open_room()
        self.assertEqual(first.room_id, second.room_id)

    def test_opening_a_room_is_audited(self):
        room = self.open_room()
        entries = [entry for entry in self.audit.entries
                   if entry.action == "video.room_open" and entry.resource_id == room.room_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, "success")

    def test_a_refused_opening_is_audited(self):
        with self.assertRaises(AuthorizationError):
            self.service.open_room(self.patient, self.appointment.appointment_id)
        denials = [entry for entry in self.audit.entries if entry.outcome == "denied"]
        self.assertTrue(denials)


class JoiningTest(VideoTestCase):
    def test_only_the_booked_patient_and_the_clinician_may_join(self):
        room = self.open_room()
        self.assertEqual(self.service.join(self.patient, room.room_id).status,
                         PARTICIPANT_WAITING)
        self.assertEqual(self.service.join(self.practitioner, room.room_id).admitted, True)

    def test_a_stranger_cannot_join(self):
        room = self.open_room()
        with self.assertRaises(AuthorizationError):
            self.service.join(self.stranger, room.room_id)

    def test_a_refused_join_is_audited(self):
        room = self.open_room()
        with self.assertRaises(AuthorizationError):
            self.service.join(self.stranger, room.room_id)
        denials = [entry for entry in self.audit.entries
                   if entry.action == "video.join" and entry.outcome == "denied"]
        self.assertTrue(denials)

    def test_the_patient_waits_for_the_clinician(self):
        room = self.open_room()
        result = self.service.join(self.patient, room.room_id)
        self.assertEqual(result.status, PARTICIPANT_WAITING)
        self.assertFalse(result.admitted)
        self.assertTrue(result.retryable)
        self.assertEqual(result.retry_after_seconds, 15)

    def test_the_clinician_admits_the_patient(self):
        room = self.open_room()
        self.service.join(self.patient, room.room_id)
        admitted = self.service.admit(self.practitioner, room.room_id, self.patient.user_id)
        self.assertEqual(admitted.participant_status(self.patient.user_id), PARTICIPANT_ADMITTED)

    def test_the_clinician_sees_who_is_waiting(self):
        room = self.open_room()
        self.service.join(self.patient, room.room_id)
        state = self.service.room_state(self.practitioner, room.room_id)
        self.assertEqual(state["waiting"], [self.patient.user_id])

    def test_the_patient_does_not_see_who_is_waiting(self):
        room = self.open_room()
        self.service.join(self.patient, room.room_id)
        state = self.service.room_state(self.patient, room.room_id)
        self.assertNotIn("waiting", state)
        self.assertEqual(state["your_status"], PARTICIPANT_WAITING)

    def test_a_patient_cannot_admit_themselves(self):
        room = self.open_room()
        self.service.join(self.patient, room.room_id)
        with self.assertRaises(AuthorizationError):
            self.service.admit(self.patient, room.room_id, self.patient.user_id)

    def test_another_clinician_cannot_admit(self):
        room = self.open_room()
        self.service.join(self.patient, room.room_id)
        with self.assertRaises(AuthorizationError):
            self.service.admit(self.other_clinician, room.room_id, self.patient.user_id)

    def test_a_stranger_cannot_see_the_room(self):
        room = self.open_room()
        with self.assertRaises(AuthorizationError):
            self.service.room_state(self.stranger, room.room_id)

    def test_an_unknown_room_is_refused(self):
        with self.assertRaises(ValidationError):
            self.service.join(self.patient, "room-nobody")


class WindowTest(VideoTestCase):
    """The room is only available inside the appointment window."""

    def setUp(self):
        super().setUp()
        self.room = self.open_room()

    def test_joining_before_the_window_is_refused_with_a_retry_path(self):
        self.clock.now = NOW - timedelta(minutes=20)
        with self.assertRaises(JoinUnavailable) as caught:
            self.service.join(self.patient, self.room.room_id)
        self.assertEqual(caught.exception.reason, "room_not_open_yet")
        self.assertTrue(caught.exception.retryable)
        self.assertGreater(caught.exception.retry_after_seconds, 0)

    def test_joining_just_before_the_window_is_allowed(self):
        # The room opens a quarter of an hour before the appointment.
        self.clock.now = NOW - timedelta(minutes=5)
        result = self.service.join(self.patient, self.room.room_id)
        self.assertEqual(result.status, PARTICIPANT_WAITING)

    def test_joining_after_the_window_is_refused_and_is_not_retryable(self):
        self.clock.now = NOW + timedelta(hours=1)
        with self.assertRaises(JoinUnavailable) as caught:
            self.service.join(self.patient, self.room.room_id)
        self.assertEqual(caught.exception.reason, "consultation_ended")
        self.assertFalse(caught.exception.retryable)

    def test_joining_just_after_the_window_is_still_allowed(self):
        self.clock.now = NOW + timedelta(minutes=40)
        result = self.service.join(self.patient, self.room.room_id)
        self.assertEqual(result.status, PARTICIPANT_WAITING)

    def test_the_room_state_says_when_it_is_closed(self):
        self.clock.now = NOW + timedelta(hours=1)
        state = self.service.room_state(self.practitioner, self.room.room_id)
        self.assertEqual(state["status"], ROOM_CLOSED)

    def test_the_room_is_open_once_somebody_is_in_it(self):
        self.service.join(self.practitioner, self.room.room_id)
        state = self.service.room_state(self.practitioner, self.room.room_id)
        self.assertEqual(state["status"], ROOM_OPEN)


class JoinTokenTest(VideoTestCase):
    def setUp(self):
        super().setUp()
        self.room = self.open_room()

    def test_an_admitted_participant_gets_a_token(self):
        self.service.join(self.practitioner, self.room.room_id)
        token = self.service.issue_join_token(self.practitioner, self.room.room_id)
        self.assertTrue(token.token)
        self.assertEqual(token.room_id, self.room.room_id)
        self.assertEqual(token.user_id, self.practitioner.user_id)

    def test_a_patient_who_is_not_admitted_gets_no_token(self):
        self.service.join(self.patient, self.room.room_id)
        with self.assertRaises(JoinUnavailable) as caught:
            self.service.issue_join_token(self.patient, self.room.room_id)
        self.assertEqual(caught.exception.reason, "not_admitted")
        self.assertTrue(caught.exception.retryable)

    def test_the_token_verifies(self):
        self.service.join(self.practitioner, self.room.room_id)
        token = self.service.issue_join_token(self.practitioner, self.room.room_id)
        claims = self.service.verify_join_token(token.token)
        self.assertEqual(claims["room"], self.room.room_id)
        self.assertEqual(claims["user"], self.practitioner.user_id)

    def test_a_tampered_token_does_not_verify(self):
        self.service.join(self.practitioner, self.room.room_id)
        token = self.service.issue_join_token(self.practitioner, self.room.room_id)
        payload, _, signature = token.token.partition(".")
        tampered = f"{payload}x.{signature}"
        with self.assertRaises(ValidationError):
            self.service.verify_join_token(tampered)

    def test_a_token_signed_with_another_rooms_secret_does_not_verify(self):
        # Each room has its own secret, so a token signed for one room cannot
        # be used for another, even by someone who knows both rooms.
        second_slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 21, 15, 0),
            local_end=datetime(2026, 10, 21, 15, 30), timezone_name="Europe/Berlin")
        second_appointment = self.booking.book(self.patient, second_slot.slot_id)
        other_room = self.service.open_room(self.practitioner,
                                            second_appointment.appointment_id)

        self.service.join(self.practitioner, self.room.room_id)
        token = self.service.issue_join_token(self.practitioner, self.room.room_id)
        _room_id, claims = self.service._decode(token.token)
        forged = self.service._sign(claims, other_room.secret)
        with self.assertRaises(ValidationError):
            self.service.verify_join_token(forged)

    def test_an_expired_token_does_not_verify(self):
        self.service.join(self.practitioner, self.room.room_id)
        token = self.service.issue_join_token(self.practitioner, self.room.room_id)
        self.clock.advance(minutes=6)
        with self.assertRaises(ValidationError):
            self.service.verify_join_token(token.token)

    def test_a_malformed_token_is_refused(self):
        with self.assertRaises(ValidationError):
            self.service.verify_join_token("not-a-token")

    def test_issuing_a_token_is_audited(self):
        self.service.join(self.practitioner, self.room.room_id)
        self.service.issue_join_token(self.practitioner, self.room.room_id)
        entries = [entry for entry in self.audit.entries if entry.action == "video.join_token"]
        self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()

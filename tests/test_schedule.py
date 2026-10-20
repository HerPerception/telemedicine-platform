"""Tests for the schedule: slots, local times and daylight saving.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.authorization import Authorizer
from telemedicine.booking import (
    MAX_SLOT_DURATION,
    Slot,
    SlotService,
    SlotTimeError,
    resolve_local_time,
    to_local_time,
)
from telemedicine.errors import ValidationError
from telemedicine.models import Role, UserAccount

BERLIN = "Europe/Berlin"
NEW_YORK = "America/New_York"


def practitioner_account(user_id="user-practitioner", record_id="practitioner-1"):
    return UserAccount(
        user_id=user_id,
        email=f"{user_id}@example.org",
        role=Role.PRACTITIONER,
        password_hash="pbkdf2_sha256$1000$abc$def",
        record_id=record_id,
    )


class LocalTimeResolutionTest(unittest.TestCase):
    def test_a_local_time_resolves_to_the_right_utc_instant(self):
        instant = resolve_local_time(datetime(2026, 7, 1, 14, 0), BERLIN)
        self.assertEqual(instant, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))

    def test_winter_and_summer_use_different_offsets(self):
        summer = resolve_local_time(datetime(2026, 7, 1, 12, 0), BERLIN)
        winter = resolve_local_time(datetime(2026, 1, 15, 12, 0), BERLIN)
        self.assertEqual(summer, datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(winter, datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc))

    def test_a_local_time_in_a_gap_does_not_exist_and_is_refused(self):
        # In Berlin the clocks jump from 02:00 to 03:00 on 2026-03-29.
        with self.assertRaises(SlotTimeError) as caught:
            resolve_local_time(datetime(2026, 3, 29, 2, 30), BERLIN)
        self.assertIn("does not exist", str(caught.exception))

    def test_a_local_time_in_an_overlap_must_be_disambiguated(self):
        # In Berlin the clocks fall back from 03:00 to 02:00 on 2026-10-25,
        # so 02:30 happens twice.
        with self.assertRaises(SlotTimeError) as caught:
            resolve_local_time(datetime(2026, 10, 25, 2, 30), BERLIN)
        self.assertIn("happens twice", str(caught.exception))

    def test_an_overlap_can_be_resolved_explicitly(self):
        first = resolve_local_time(datetime(2026, 10, 25, 2, 30), BERLIN, fold=0)
        second = resolve_local_time(datetime(2026, 10, 25, 2, 30), BERLIN, fold=1)
        self.assertNotEqual(first, second)
        self.assertEqual(second - first, timedelta(hours=1))

    def test_an_unknown_zone_is_refused(self):
        with self.assertRaises(SlotTimeError):
            resolve_local_time(datetime(2026, 7, 1, 12, 0), "Mars/Olympus_Mons")

    def test_an_aware_local_time_is_refused(self):
        with self.assertRaises(SlotTimeError):
            resolve_local_time(datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc), BERLIN)

    def test_an_instant_renders_back_in_the_local_zone(self):
        instant = resolve_local_time(datetime(2026, 7, 1, 14, 0), BERLIN)
        local = to_local_time(instant, BERLIN)
        self.assertEqual(local.replace(tzinfo=None), datetime(2026, 7, 1, 14, 0))
        self.assertEqual(local.utcoffset(), timedelta(hours=2))

    def test_the_same_instant_is_the_same_instant_in_every_zone(self):
        instant = resolve_local_time(datetime(2026, 7, 1, 14, 0), BERLIN)
        in_new_york = to_local_time(instant, NEW_YORK)
        self.assertEqual(in_new_york.replace(tzinfo=None), datetime(2026, 7, 1, 8, 0))


class SlotServiceTest(unittest.TestCase):
    def setUp(self):
        self.service = SlotService()
        self.practitioner = practitioner_account()
        self.patient = UserAccount(
            user_id="user-patient",
            email="user-patient@example.org",
            role=Role.PATIENT,
            password_hash="pbkdf2_sha256$1000$abc$def",
            record_id="patient-1",
        )

    def create_slot(self, start=datetime(2026, 7, 1, 14, 0), end=None, timezone_name=BERLIN,
                    actor=None, fold=None):
        end = end or (start + timedelta(minutes=30))
        return self.service.create_slot(
            actor or self.practitioner,
            practitioner_id="practitioner-1",
            local_start=start,
            local_end=end,
            timezone_name=timezone_name,
            fold=fold,
        )

    def test_a_slot_is_stored_as_utc_and_keeps_its_zone(self):
        slot = self.create_slot()
        self.assertEqual(slot.starts_at, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(slot.ends_at, datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc))
        self.assertEqual(slot.timezone, BERLIN)
        self.assertEqual(slot.status, "free")

    def test_a_patient_cannot_open_a_slot(self):
        from telemedicine.errors import AuthorizationError
        with self.assertRaises(AuthorizationError):
            self.create_slot(actor=self.patient)

    def test_two_slots_of_the_same_practitioner_may_not_overlap(self):
        self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        with self.assertRaises(ValidationError):
            self.create_slot(start=datetime(2026, 7, 1, 14, 15))

    def test_two_slots_of_different_practitioners_may_overlap(self):
        self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        other = practitioner_account("user-other", "practitioner-2")
        slot = self.service.create_slot(
            other, practitioner_id="practitioner-2",
            local_start=datetime(2026, 7, 1, 14, 0),
            local_end=datetime(2026, 7, 1, 14, 30),
            timezone_name=BERLIN)
        self.assertEqual(slot.practitioner_id, "practitioner-2")

    def test_a_slot_must_end_after_it_starts(self):
        with self.assertRaises(ValidationError):
            self.create_slot(start=datetime(2026, 7, 1, 14, 0),
                             end=datetime(2026, 7, 1, 13, 0))

    def test_a_slot_may_not_be_longer_than_the_maximum(self):
        with self.assertRaises(ValidationError):
            self.create_slot(start=datetime(2026, 7, 1, 8, 0),
                             end=datetime(2026, 7, 1, 8, 0) + MAX_SLOT_DURATION + timedelta(minutes=1))

    def test_a_slot_starts_and_ends_on_a_whole_minute(self):
        with self.assertRaises(ValidationError):
            self.create_slot(start=datetime(2026, 7, 1, 14, 0, 30))

    def test_free_slots_are_listed_in_start_order(self):
        first = self.create_slot(start=datetime(2026, 7, 2, 14, 0))
        second = self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        listed = self.service.list_free_slots("practitioner-1")
        self.assertEqual([slot.slot_id for slot in listed],
                         [second.slot_id, first.slot_id])

    def test_free_slots_can_be_filtered_by_a_utc_window(self):
        self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        self.create_slot(start=datetime(2026, 7, 2, 14, 0))
        window_start = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
        listed = self.service.list_free_slots("practitioner-1", after=window_start)
        self.assertEqual(len(listed), 1)

    def test_a_slot_can_be_found_by_its_local_time(self):
        self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        found = self.service.slot_for_local_time("practitioner-1",
                                                 datetime(2026, 7, 1, 14, 15), BERLIN)
        self.assertIsNotNone(found)
        self.assertEqual(found.practitioner_id, "practitioner-1")

    def test_a_local_time_outside_every_slot_finds_nothing(self):
        self.create_slot(start=datetime(2026, 7, 1, 14, 0))
        self.assertIsNone(self.service.slot_for_local_time(
            "practitioner-1", datetime(2026, 7, 1, 20, 0), BERLIN))

    def test_creating_a_slot_is_audited(self):
        slot = self.create_slot()
        entries = [entry for entry in self.service.audit.entries
                   if entry.resource_id == slot.slot_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].action, "slot.create")

    def test_a_refused_slot_creation_is_audited(self):
        from telemedicine.errors import AuthorizationError
        with self.assertRaises(AuthorizationError):
            self.create_slot(actor=self.patient)
        denials = [entry for entry in self.service.audit.entries
                   if entry.outcome == "denied"]
        self.assertEqual(len(denials), 1)

    def test_a_booked_slot_cannot_be_closed(self):
        slot = self.create_slot()
        self.service._set_status(slot.slot_id, "busy")
        with self.assertRaises(ValidationError):
            self.service.close_slot(self.practitioner, slot.slot_id)

    def test_a_free_slot_can_be_closed(self):
        slot = self.create_slot()
        closed = self.service.close_slot(self.practitioner, slot.slot_id)
        self.assertEqual(closed.status, "entered-in-error")
        self.assertEqual(self.service.list_free_slots("practitioner-1"), [])


if __name__ == "__main__":
    unittest.main()

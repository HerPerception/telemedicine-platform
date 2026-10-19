"""Tests for the append-only, tamper-evident audit log.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import dataclasses
import unittest
from datetime import datetime, timezone

from telemedicine.audit import (
    GENESIS_HASH,
    OUTCOME_DENIED,
    OUTCOME_ERROR,
    OUTCOME_SUCCESS,
    AuditLog,
    hash_payload,
)
from telemedicine.errors import AuditError


class FakeClock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        from datetime import timedelta
        self.now = self.now + timedelta(**kwargs)
        return self.now


def append_entry(log, **overrides):
    payload = {
        "actor_user_id": "user-1",
        "actor_role": "patient",
        "action": "record.read",
        "resource_type": "patient",
        "resource_id": "patient-1",
        "outcome": OUTCOME_SUCCESS,
        "detail": "read patient record patient-1",
    }
    payload.update(overrides)
    return log.append(**payload)


class AuditLogTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.log = AuditLog(clock=self.clock)

    def test_a_new_log_is_empty_and_valid(self):
        self.assertEqual(len(self.log), 0)
        self.assertTrue(self.log.verify_chain())
        self.assertIsNone(self.log.find_chain_break())

    def test_entries_are_numbered_from_one_and_link_to_their_predecessor(self):
        first = append_entry(self.log)
        second = append_entry(self.log, resource_id="patient-2")
        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(first.previous_hash, GENESIS_HASH)
        self.assertEqual(second.previous_hash, first.entry_hash)

    def test_timestamps_are_utc_iso8601(self):
        entry = append_entry(self.log)
        self.assertTrue(entry.occurred_at.endswith("Z"))
        parsed = datetime.fromisoformat(entry.occurred_at.replace("Z", "+00:00"))
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_an_unknown_outcome_is_refused(self):
        with self.assertRaises(AuditError):
            self.log.append(actor_user_id="user-1", actor_role="patient",
                            action="record.read", resource_type="patient",
                            resource_id="patient-1", outcome="maybe")

    def test_entries_cannot_be_mutated(self):
        entry = append_entry(self.log)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.detail = "tampered"

    def test_the_entry_list_is_a_snapshot(self):
        append_entry(self.log)
        entries = self.log.entries
        append_entry(self.log)
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(self.log.entries), 2)

    def test_filters(self):
        append_entry(self.log, resource_id="patient-1")
        append_entry(self.log, resource_id="patient-2", outcome=OUTCOME_DENIED)
        append_entry(self.log, actor_user_id="user-2", resource_id="patient-3")
        self.assertEqual(len(self.log.entries_for_resource("patient", "patient-1")), 1)
        self.assertEqual(len(self.log.entries_for_actor("user-2")), 1)
        self.assertEqual(len(self.log.entries_for_outcome(OUTCOME_DENIED)), 1)
        self.assertEqual(len(self.log.entries_for_outcome(OUTCOME_SUCCESS)), 2)
        self.assertEqual(len(self.log.entries_for_resource("patient", "patient-9")), 0)

    def test_error_outcome_is_supported(self):
        entry = append_entry(self.log, outcome=OUTCOME_ERROR)
        self.assertEqual(entry.outcome, OUTCOME_ERROR)


class TamperDetectionTest(unittest.TestCase):
    """The point of the hash chain: altered entries must be detectable."""

    def setUp(self):
        self.log = AuditLog(clock=FakeClock())
        for index in range(3):
            append_entry(self.log, resource_id=f"patient-{index}")

    def test_an_untouched_log_verifies(self):
        self.assertTrue(self.log.verify_chain())
        self.assertIsNone(self.log.find_chain_break())

    def test_an_altered_entry_is_detected(self):
        entries = list(self.log.entries)
        altered = dataclasses.replace(entries[1], detail="changed after the fact")
        tampered = AuditLog(entries=[entries[0], altered, entries[2]])
        self.assertFalse(tampered.verify_chain())
        self.assertEqual(tampered.find_chain_break(), 2)

    def test_a_deleted_entry_is_detected(self):
        entries = list(self.log.entries)
        tampered = AuditLog(entries=[entries[0], entries[2]])
        self.assertFalse(tampered.verify_chain())
        self.assertEqual(tampered.find_chain_break(), 3)

    def test_a_replaced_entry_hash_is_detected(self):
        entries = list(self.log.entries)
        altered = dataclasses.replace(entries[0], entry_hash="0" * 64)
        tampered = AuditLog(entries=[altered, entries[1], entries[2]])
        self.assertFalse(tampered.verify_chain())

    def test_appending_to_a_broken_log_is_refused(self):
        entries = list(self.log.entries)
        altered = dataclasses.replace(entries[0], detail="changed")
        tampered = AuditLog(entries=[altered, entries[1], entries[2]])
        with self.assertRaises(AuditError):
            append_entry(tampered)

    def test_the_hash_covers_the_content_of_the_entry(self):
        entry = self.log.entries[0]
        payload = entry.payload()
        payload["detail"] = "something else"
        self.assertNotEqual(hash_payload(payload), entry.entry_hash)

    def test_two_logs_start_from_the_same_genesis_link(self):
        # The first entry of every chain links to the genesis hash; that is
        # what makes a chain a chain rather than a set of unrelated rows.
        other = AuditLog(clock=FakeClock())
        append_entry(other)
        self.assertEqual(other.entries[0].previous_hash, self.log.entries[0].previous_hash)
        self.assertEqual(other.entries[0].previous_hash, GENESIS_HASH)


if __name__ == "__main__":
    unittest.main()

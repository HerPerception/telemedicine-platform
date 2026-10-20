"""Tests for the audit chain anchor.

The point of the anchor is that a chain rewritten *from the beginning* cannot
be told apart from an untouched one by looking at the chain alone. These
tests do exactly that rewrite, and check that it is caught.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tests.test_persistence import _fresh_database

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=NOW):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        from datetime import timedelta
        self.now = self.now + timedelta(**kwargs)
        return self.now


def write_entries(log, count=5, actor=None):
    for index in range(count):
        log.append(
            actor_user_id=actor or str(uuid.uuid4()),
            actor_role="patient",
            action="record.read",
            resource_type="patient",
            resource_id=f"patient-{index}",
            outcome="success",
            detail=f"read patient-{index}")


class AnchorFileTest(unittest.TestCase):
    def test_an_anchor_is_written_to_the_file(self):
        from telemedicine.audit_anchor import Anchor, FileAuditAnchor

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchors.jsonl"
            store = FileAuditAnchor(path)
            anchor = Anchor(sequence=7, entry_hash="a" * 64, chain_head="b" * 64,
                             anchored_at=NOW)
            store.publish(anchor)

            self.assertTrue(path.exists())
            anchors = FileAuditAnchor(path).anchors()
            self.assertEqual(len(anchors), 1)
            self.assertEqual(anchors[0].sequence, 7)
            self.assertEqual(anchors[0].entry_hash, "a" * 64)
            self.assertEqual(anchors[0].anchored_at, NOW)

    def test_the_file_is_appended_to_and_never_rewritten(self):
        from telemedicine.audit_anchor import Anchor, FileAuditAnchor

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchors.jsonl"
            store = FileAuditAnchor(path)
            for index in range(3):
                store.publish(Anchor(sequence=index, entry_hash=f"{index}" * 64,
                                     chain_head="c" * 64, anchored_at=NOW))
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)

    def test_a_line_that_cannot_be_read_does_not_lose_the_others(self):
        from telemedicine.audit_anchor import Anchor, FileAuditAnchor

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchors.jsonl"
            store = FileAuditAnchor(path)
            store.publish(Anchor(sequence=1, entry_hash="a" * 64, chain_head="b" * 64,
                                 anchored_at=NOW))
            with path.open("a", encoding="utf-8") as handle:
                handle.write("this is not an anchor\n")
            store.publish(Anchor(sequence=2, entry_hash="c" * 64, chain_head="d" * 64,
                                 anchored_at=NOW))
            anchors = FileAuditAnchor(path).anchors()
            self.assertEqual([anchor.sequence for anchor in anchors], [1, 2])


class AnchoredLogTest(unittest.TestCase):
    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.audit_anchor import AnchoredAuditLog, InMemoryAuditAnchor

        self.clock = FakeClock()
        self.anchors = InMemoryAuditAnchor()
        self.log = AnchoredAuditLog(AuditLog(clock=self.clock), self.anchors, every=3,
                                    clock=self.clock)

    def test_an_anchor_is_published_every_so_often(self):
        write_entries(self.log, count=3)
        self.assertEqual(len(self.anchors.anchors()), 1)

    def test_the_anchor_names_the_head_of_the_chain(self):
        write_entries(self.log, count=3)
        anchor = self.anchors.anchors()[0]
        self.assertEqual(anchor.entry_hash, self.log.head_hash())
        self.assertEqual(anchor.sequence, 3)

    def test_nothing_is_published_before_the_first_anchor_is_due(self):
        write_entries(self.log, count=2)
        self.assertEqual(self.anchors.anchors(), [])

    def test_the_log_still_behaves_like_a_log(self):
        write_entries(self.log, count=1)
        self.assertEqual(len(self.log), 1)
        self.assertTrue(self.log.verify_chain())


class VerifyTest(unittest.TestCase):
    """The check that a rewritten chain is caught."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.audit_anchor import AnchoredAuditLog, InMemoryAuditAnchor

        self.clock = FakeClock()
        self.anchors = InMemoryAuditAnchor()
        self.log = AnchoredAuditLog(AuditLog(clock=self.clock), self.anchors, every=2,
                                    clock=self.clock)
        write_entries(self.log, count=4)

    def test_an_untouched_log_agrees_with_its_anchors(self):
        from telemedicine.audit_anchor import verify_anchors

        self.assertEqual(verify_anchors(self.log, self.anchors), [])
        self.assertTrue(self.log.verify_chain())

    def test_a_rewritten_chain_is_caught_by_the_anchors(self):
        import dataclasses
        from telemedicine.audit_anchor import verify_anchors

        # What an attacker with write access to the log would do: replace the
        # entries, and rebuild the chain so that it verifies again.
        entries = self.log.entries
        rewritten = tuple(
            dataclasses.replace(entry, detail="something else that still hashes")
            if entry.sequence == 2 else entry
            for entry in entries)
        # The chain of the rewritten log is rebuilt so that it verifies.
        from telemedicine.audit import hash_payload
        previous = "0" * 64
        rebuilt = []
        for index, entry in enumerate(rewritten, start=1):
            payload = entry.payload()
            payload["sequence"] = index
            payload["previous_hash"] = previous
            entry_hash = hash_payload(payload)
            rebuilt.append(dataclasses.replace(entry, sequence=index,
                                               previous_hash=previous,
                                               entry_hash=entry_hash))
            previous = entry_hash

        from telemedicine.audit_anchor import verify_anchors
        problems = verify_anchors(rebuilt, self.anchors)
        self.assertTrue(problems, "a rewritten chain must be caught by the anchors")
        self.assertIn("does not match the anchor", " ".join(problems))

    def test_a_missing_anchor_is_reported(self):
        from telemedicine.audit_anchor import InMemoryAuditAnchor, verify_anchors

        problems = verify_anchors(self.log, InMemoryAuditAnchor())
        self.assertEqual(len(problems), 1)
        self.assertIn("no anchors", problems[0])

    def test_an_entry_that_is_gone_is_reported(self):
        from telemedicine.audit_anchor import verify_anchors

        # A log that has lost the anchored entry.
        trimmed = [entry for entry in self.log.entries if entry.sequence != 2]
        problems = verify_anchors(trimmed, self.anchors)
        self.assertTrue(problems)
        self.assertIn("not in the log", " ".join(problems))


class DurableAnchorTest(unittest.TestCase):
    """The anchors live outside the database, and the operator can check them."""

    def setUp(self):
        self.database = _fresh_database("telemedicine_anchor_test")
        if self.database is None:
            raise unittest.SkipTest("no PostgreSQL: set TELEMEDICINE_TEST_DSN")

    def test_a_chain_rewritten_in_the_database_is_caught(self):
        import dataclasses
        from telemedicine.audit_anchor import (
            AnchoredAuditLog,
            FileAuditAnchor,
            verify_anchors,
        )
        from telemedicine.persistence.audit_store import PostgresAuditLog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchors.jsonl"
            anchors = FileAuditAnchor(path)
            log = AnchoredAuditLog(PostgresAuditLog(self.database), anchors, every=2)

            write_entries(log, count=4)
            self.assertEqual(len(anchors.anchors()), 2)
            self.assertEqual(verify_anchors(log, anchors), [])

            # Now the attacker: every entry from the second onwards is
            # rewritten and the chain is rebuilt from there, so that the
            # chain verifies again. This is the case the internal check
            # cannot see, and the reason the anchor exists.
            from telemedicine.audit import hash_payload

            entries = list(log.entries)
            previous = entries[0].entry_hash
            rewritten = [entries[0]]
            for entry in entries[1:]:
                payload = entry.payload()
                payload["detail"] = "rewritten by an attacker"
                payload["previous_hash"] = previous
                entry_hash = hash_payload(payload)
                rewritten.append(dataclasses.replace(entry, detail=payload["detail"],
                                                    previous_hash=previous,
                                                    entry_hash=entry_hash))
                previous = entry_hash

            with self.database.transaction() as cursor:
                cursor.execute(
                    "ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_or_delete")
                for entry in rewritten[1:]:
                    cursor.execute(
                        "UPDATE audit_log SET detail = %s, previous_hash = %s, entry_hash = %s"
                        " WHERE sequence = %s",
                        (entry.detail, entry.previous_hash, entry.entry_hash, entry.sequence))
                cursor.execute(
                    "ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_or_delete")

            # The chain itself verifies again — that is the point.
            self.assertTrue(log.verify_chain())
            # And the anchor catches it.
            problems = verify_anchors(log, anchors)
            self.assertTrue(problems, "the rewrite must be caught")
            self.assertIn("does not match the anchor", " ".join(problems))


if __name__ == "__main__":
    unittest.main()

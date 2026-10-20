"""Tests for the breach report.

Section 40(2) of the Nigeria Data Protection Act 2023 says that a data
controller must notify the Commission of a breach within 72 hours, and
describe it "including the categories and approximate numbers of data
subjects and personal data records concerned".

The script assembles the half of that which is a matter of fact — who was
affected, how many records, what was done with them — and leaves the half
which is a judgment to the person writing the report. These tests hold it
to that division.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import importlib.util
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemedicine.audit import AuditLog

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_script():
    """Import ``scripts/report_breach.py`` by path."""
    path = REPO_ROOT / "scripts" / "report_breach.py"
    spec = importlib.util.spec_from_file_location("report_breach", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now


START = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)


class BreachReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_script()

    def setUp(self):
        self.clock = Clock(START)
        self.log = AuditLog(clock=self.clock)
        self.patient = str(uuid.uuid4())
        self.other = str(uuid.uuid4())
        self.log.append(actor_user_id=self.patient, actor_role="practitioner",
                        action="record.view", resource_type="patient",
                        resource_id=self.patient, detail="opened the chart")
        self.clock.now = START + timedelta(hours=1)
        self.log.append(actor_user_id=self.patient, actor_role="patient",
                        action="prescription.read", resource_type="prescription",
                        resource_id="doc-1", detail="")
        self.clock.now = START + timedelta(hours=2)
        self.log.append(actor_user_id=self.other, actor_role="practitioner",
                        action="record.view", resource_type="patient",
                        resource_id=self.other, detail="")

    def report(self, since=None, until=None, nature="an account was read "
                                                     "that should not have been",
               records=None):
        since = since or START - timedelta(minutes=1)
        until = until or START + timedelta(hours=3)
        return self.script.build_report(self.log, since, until, nature,
                                         records or [])

    # -- the facts ---------------------------------------------------------

    def test_the_report_counts_the_data_subjects(self):
        report = self.report()
        self.assertIn("Data subjects (accounts with records touched): 2",
                      report)
        self.assertIn(self.patient, report)
        self.assertIn(self.other, report)

    def test_the_report_counts_the_records(self):
        report = self.report()
        self.assertIn("Personal data records concerned: 3", report)

    def test_the_report_says_what_was_done_with_them(self):
        report = self.report()
        self.assertIn("record.view: 2", report)
        self.assertIn("prescription.read: 1", report)

    def test_the_report_states_the_nature(self):
        report = self.report()
        self.assertIn("an account was read that should not have been", report)

    def test_the_records_the_controller_believes_were_affected_are_listed(self):
        report = self.report(records=["patient-42"])
        self.assertIn("patient-42", report)

    # -- the window --------------------------------------------------------

    def test_entries_outside_the_window_are_left_out(self):
        report = self.report(until=START + timedelta(minutes=30))
        self.assertIn("Access events in the window: 1", report)
        self.assertIn("Data subjects (accounts with records touched): 1",
                      report)

    def test_the_window_is_stated_on_the_report(self):
        report = self.report()
        self.assertIn("Window:", report)

    # -- the instants ------------------------------------------------------

    def test_an_instant_written_as_text_is_read(self):
        # The audit log keeps its instants as text, because that is what
        # the hash chain is computed over.
        self.assertEqual(self.script.moment("2026-10-21T08:00:00Z"), START)

    def test_an_instant_given_as_a_datetime_is_read(self):
        self.assertEqual(self.script.moment(START), START)

    def test_an_instant_without_a_timezone_is_read_as_utc(self):
        naive = datetime(2026, 10, 21, 8, 0)
        self.assertEqual(self.script.moment(naive), START)

    def test_the_window_arguments_are_parsed(self):
        moment = self.script.parse_moment("2026-10-21T08:00:00Z")
        self.assertEqual(moment, START)
        self.assertEqual(self.script.parse_moment("2026-10-21T08:00:00"),
                         START)

    # -- what the report does not claim ------------------------------------

    def test_the_report_says_what_the_controller_must_still_write(self):
        report = self.report()
        self.assertIn("TO BE COMPLETED BY THE CONTROLLER", report)
        self.assertIn("Likely consequences", report)
        self.assertIn("Measures taken or proposed", report)

    def test_the_report_names_the_seventy_two_hour_rule(self):
        report = self.report()
        self.assertIn("72 hours", report)

    def test_the_report_says_it_is_a_drafting_aid(self):
        report = self.report()
        self.assertIn("drafting aid", report)

    def test_the_report_says_a_high_risk_breach_is_told_to_the_patient_at_once(self):
        report = self.report()
        self.assertIn("HIGH risk", report)
        self.assertIn("immediately", report)


if __name__ == "__main__":
    unittest.main()

"""Tests for the demo mode and the legal to-do list.

**The demo mode is on by default.** The practice has no legal adviser yet,
and a prescription that could be mistaken for a real one is worse than one
that says plainly on its face that it is not.

These tests hold two things to that: the watermark is on the document by
default, and it comes off only when the practice says so.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from pathlib import Path

from telemedicine.config import Settings
from telemedicine.prescriptions import DEMO_WATERMARK

REPO_ROOT = Path(__file__).resolve().parent.parent


class TheSettingTest(unittest.TestCase):
    """The setting itself."""

    def test_the_demo_mode_is_on_by_default(self):
        self.assertTrue(Settings().demo_mode)

    def test_it_can_be_turned_off(self):
        settings = Settings.from_environment({"TELEMEDICINE_DEMO_MODE": "false"})
        self.assertFalse(settings.demo_mode)

    def test_it_can_be_turned_off_in_the_usual_ways(self):
        for value in ("0", "false", "no", "off", "FALSE"):
            with self.subTest(value=value):
                settings = Settings.from_environment({"TELEMEDICINE_DEMO_MODE": value})
                self.assertFalse(settings.demo_mode)

    def test_it_stays_on_when_the_environment_says_nothing(self):
        settings = Settings.from_environment({})
        self.assertTrue(settings.demo_mode)


class TheWatermarkTest(unittest.TestCase):
    """The document says it is not for real patients."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService, SlotService
        from telemedicine.models import Role
        from telemedicine.prescriptions import PrescriptionService
        from telemedicine.records import (
            Encounter,
            PatientRecord,
            PractitionerRecord,
            RecordsService,
        )

        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.booking = BookingService(self.slots, audit=self.audit,
                                      records=self.records)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.patient = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.practitioner = self.auth.register("dr@example.org", "a-long-passphrase",
                                               Role.PRACTITIONER,
                                               record_id="practitioner-1")
        self.records.add_patient(PatientRecord(
            patient_id="patient-1", user_id=self.patient.user_id,
            display_name="Ada Nwosu Okonkwo"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id=self.practitioner.user_id,
            display_name="Dr. Elena Ramirez"))
        self.records.add_encounter(Encounter(
            encounter_id="encounter-1", appointment_id="appointment-1",
            patient_id="patient-1", practitioner_id="practitioner-1",
            patient_user_id=self.patient.user_id,
            practitioner_user_id=self.practitioner.user_id,
            status="finished", started_at=_now(), ended_at=_now()))

    def service(self, demo_mode=True):
        from telemedicine.prescriptions import PrescriptionService
        return PrescriptionService(self.records, audit=self.audit,
                                   demo_mode=demo_mode)

    def issue(self, service):
        prescription, document = service.issue(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule three times a day for 5 days.",
            brand_name="Emoclox", generic_name="Amoxicillin 500mg",
            strength="500mg Capsules", nafdac_number="A4-1234")
        return prescription, document

    def test_the_document_carries_the_watermark(self):
        _prescription, document = self.issue(self.service())
        text = document.body.decode("latin-1")
        self.assertIn(DEMO_WATERMARK, text)

    def test_the_watermark_is_bold(self):
        _prescription, document = self.issue(self.service())
        text = document.body.decode("latin-1")
        self.assertIn(f"({DEMO_WATERMARK}) Tj", text)
        self.assertIn("/F2", text)

    def test_the_watermark_is_near_the_top(self):
        _prescription, document = self.issue(self.service())
        text = document.body.decode("latin-1")
        self.assertLess(text.index(DEMO_WATERMARK),
                        text.index("E-PRESCRIPTION") + 200)

    def test_the_watermark_is_on_the_downloaded_document_too(self):
        # The download is the same document, so it carries the same words.
        service = self.service()
        prescription, document = self.issue(service)
        body = service.download(self.patient, prescription.prescription_id)
        self.assertIn(DEMO_WATERMARK, body.decode("latin-1"))

    def test_there_is_no_watermark_when_the_demo_mode_is_off(self):
        _prescription, document = self.issue(self.service(demo_mode=False))
        text = document.body.decode("latin-1")
        self.assertNotIn(DEMO_WATERMARK, text)

    def test_the_words_are_exactly_as_they_should_be(self):
        self.assertEqual(DEMO_WATERMARK, "DEMO - NOT FOR REAL PATIENTS")


class TheLegalToDoTest(unittest.TestCase):
    """The list of what is waiting for a lawyer."""

    @classmethod
    def setUpClass(cls):
        cls.path = REPO_ROOT / "TODO_LEGAL.md"
        cls.text = cls.path.read_text(encoding="utf-8") if cls.path.is_file() else ""

    def test_the_file_exists(self):
        self.assertTrue(self.path.is_file(),
                        "TODO_LEGAL.md is missing: the practice has to be told "
                        "what is waiting for a lawyer")

    def test_it_lists_the_retention_numbers(self):
        self.assertIn("retention", self.text.lower())
        self.assertIn("retention_policy.yaml", self.text)

    def test_it_lists_the_transfer_justifications(self):
        self.assertIn("external_services.yaml", self.text)

    def test_it_lists_the_privacy_notice(self):
        self.assertIn("privacy-notice-draft.md", self.text)

    def test_it_makes_the_recommendation(self):
        self.assertIn("Nigeria", self.text)
        self.assertIn("test data", self.text.lower())

    def test_it_says_what_changes_when_the_adviser_has_signed(self):
        self.assertIn("signed", self.text.lower())

    def test_it_says_the_demo_mode_is_on(self):
        self.assertIn("DEMO_MODE", self.text)


def _now():
    from datetime import datetime, timezone
    return datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


if __name__ == "__main__":
    unittest.main()

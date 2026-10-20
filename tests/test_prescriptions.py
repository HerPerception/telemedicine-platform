"""Tests for e-prescriptions: issuing, the document, downloading and audit.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_ERROR, OUTCOME_SUCCESS
from telemedicine.audit import AuditLog
from telemedicine.authorization import Authorizer
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.models import Role, UserAccount
from telemedicine.prescriptions import (
    ACTION_DOWNLOAD,
    ACTION_STATUS_CHANGE,
    CONTENT_TYPE_PDF,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_DRAFT,
    PrescriptionService,
    render_pdf,
)
from telemedicine.records import (
    ACTION_PRESCRIPTION_CREATE,
    ACTION_PRESCRIPTION_READ,
    Encounter,
    PatientRecord,
    PractitionerRecord,
    RecordsService,
)

NOW = datetime(2026, 10, 21, 14, 26, tzinfo=timezone.utc)


def make_account(user_id, role, record_id):
    return UserAccount(
        user_id=user_id,
        email=f"{user_id}@example.org",
        role=role,
        password_hash="pbkdf2_sha256$1000$abc$def",
        record_id=record_id,
    )


class PrescriptionTestCase(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.service = PrescriptionService(self.records, audit=self.audit, clock=lambda: NOW)

        self.patient = make_account("user-patient", Role.PATIENT, "patient-1")
        self.other_patient = make_account("user-other-patient", Role.PATIENT, "patient-2")
        self.practitioner = make_account("user-practitioner", Role.PRACTITIONER,
                                         "practitioner-1")
        self.other_practitioner = make_account("user-other-practitioner", Role.PRACTITIONER,
                                               "practitioner-2")

        self.records.add_patient(PatientRecord(patient_id="patient-1", user_id="user-patient",
                                               display_name="Ada Nwosu Okonkwo"))
        self.records.add_patient(PatientRecord(patient_id="patient-2",
                                               user_id="user-other-patient",
                                               display_name="Someone Else"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id="user-practitioner",
            display_name="Dr. Elena Ramirez", identifier="NPI 1234567893"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-2", user_id="user-other-practitioner",
            display_name="Dr. Someone Else", identifier="NPI 9876543210"))

        self.records.add_encounter(Encounter(
            encounter_id="encounter-1",
            appointment_id="appointment-1",
            patient_id="patient-1",
            practitioner_id="practitioner-1",
            patient_user_id="user-patient",
            practitioner_user_id="user-practitioner",
            status="finished",
            started_at=NOW,
            ended_at=NOW,
        ))

    def issue(self, actor=None):
        return self.service.issue(
            actor or self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="Take one capsule by mouth three times a day for 5 days.",
        )


class IssuingTest(PrescriptionTestCase):
    def test_the_treating_clinician_can_issue(self):
        prescription, document = self.issue()
        self.assertEqual(prescription.patient_id, "patient-1")
        self.assertEqual(prescription.prescriber_id, "practitioner-1")
        self.assertEqual(prescription.encounter_id, "encounter-1")
        self.assertEqual(prescription.status, STATUS_ACTIVE)
        self.assertEqual(document.content_type, CONTENT_TYPE_PDF)

    def test_a_patient_cannot_issue_a_prescription(self):
        with self.assertRaises(AuthorizationError):
            self.issue(self.patient)

    def test_a_clinician_who_did_not_treat_the_patient_cannot_issue(self):
        # The encounter belongs to practitioner-1, so practitioner-2 is not in
        # scope for it.
        with self.assertRaises(AuthorizationError):
            self.issue(self.other_practitioner)

    def test_issuing_is_audited(self):
        prescription, _ = self.issue()
        entries = [entry for entry in self.audit.entries
                   if entry.action == ACTION_PRESCRIPTION_CREATE
                   and entry.resource_id == prescription.prescription_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].outcome, OUTCOME_SUCCESS)
        self.assertEqual(entries[0].actor_user_id, "user-practitioner")

    def test_a_refused_issue_is_audited(self):
        with self.assertRaises(AuthorizationError):
            self.issue(self.patient)
        denials = [entry for entry in self.audit.entries
                   if entry.action == ACTION_PRESCRIPTION_CREATE
                   and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_a_prescription_needs_a_medication_and_dosage(self):
        with self.assertRaises(ValidationError):
            self.service.issue(self.practitioner, "encounter-1",
                               medication_code="", medication_display="",
                               dosage_text="")

    def test_the_prescription_is_tied_to_the_encounter_and_the_patient(self):
        prescription, _ = self.issue()
        self.assertEqual(prescription.patient_user_id, "user-patient")
        self.assertEqual(prescription.prescriber_user_id, "user-practitioner")
        # The patient and the prescriber are inherited from the encounter, so
        # a prescription can never be attached to another patient.
        encounter = self.records._encounters["encounter-1"]
        self.assertEqual(prescription.patient_id, encounter.patient_id)
        self.assertEqual(prescription.prescriber_id, encounter.practitioner_id)


class DocumentTest(PrescriptionTestCase):
    def test_the_document_is_a_pdf(self):
        _, document = self.issue()
        self.assertTrue(document.body.startswith(b"%PDF-1.4"))
        self.assertTrue(document.body.rstrip().endswith(b"%%EOF"))
        self.assertEqual(document.content_type, "application/pdf")

    def test_the_document_has_a_checksum_that_matches_its_bytes(self):
        _, document = self.issue()
        self.assertTrue(document.checksum_matches())
        self.assertEqual(len(document.checksum), 64)

    def test_a_tampered_document_is_detected(self):
        _, document = self.issue()
        import dataclasses
        tampered = dataclasses.replace(document, body=document.body + b"tampered")
        self.assertFalse(tampered.checksum_matches())

    def test_the_document_states_the_prescription(self):
        _, document = self.issue()
        text = document.body.decode("latin-1")
        self.assertIn("Amoxicillin 500 mg capsule", text)
        self.assertIn("AMOX-500-CAP", text)
        self.assertIn("Take one capsule by mouth three times a day for 5 days.", text)
        self.assertIn("Ada Nwosu Okonkwo", text)
        self.assertIn("Dr. Elena Ramirez", text)
        self.assertIn("E-PRESCRIPTION", text)

    def test_rendering_is_audited(self):
        prescription, _ = self.issue()
        entries = [entry for entry in self.audit.entries
                   if entry.action == "prescription.document_render"
                   and entry.resource_id == prescription.prescription_id]
        self.assertEqual(len(entries), 1)

    def test_the_renderer_escapes_parentheses_and_backslashes(self):
        body = render_pdf(["a (parenthesis) and a \\ backslash"])
        self.assertIn(r"\(parenthesis\)", body.decode("latin-1"))
        self.assertIn("\\\\", body.decode("latin-1"))

    def test_the_renderer_keeps_the_document_valid(self):
        body = render_pdf(["line one", "line two"])
        self.assertTrue(body.startswith(b"%PDF-1.4"))
        self.assertIn(b"/Type /Catalog", body)
        self.assertIn(b"/Type /Pages", body)
        self.assertIn(b"/Type /Page", body)
        self.assertIn(b"xref", body)
        self.assertIn(b"trailer", body)

    def test_the_document_renders_in_a_real_pdf_reader(self):
        """Check the document with an external PDF tool, when one is present.

        The renderer writes the PDF itself, so the only way to know that the
        file is not merely plausible but actually readable is to read it with
        something else. `pdftotext` (poppler-utils) is used when it is
        installed; the test is skipped otherwise, and the rendering evidence
        is recorded in the resolution log.
        """
        tool = shutil.which("pdftotext")
        if tool is None:
            self.skipTest("pdftotext is not installed")
        _, document = self.issue()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(document.body)
            path = handle.name
        try:
            result = subprocess.run([tool, path, "-"], capture_output=True, text=True,
                                    timeout=60, check=True)
        finally:
            os.unlink(path)
        text = result.stdout
        self.assertIn("E-PRESCRIPTION", text)
        self.assertIn("Amoxicillin 500 mg capsule", text)
        self.assertIn("Ada Nwosu Okonkwo", text)
        self.assertIn("Dr. Elena Ramirez", text)
        self.assertIn("Take one capsule by mouth three times a day for 5 days.", text)


class DownloadTest(PrescriptionTestCase):
    def test_the_patient_can_download_their_own_prescription(self):
        prescription, document = self.issue()
        body = self.service.download(self.patient, prescription.prescription_id)
        self.assertEqual(body, document.body)

    def test_the_prescriber_can_download_the_prescription(self):
        prescription, _ = self.issue()
        body = self.service.download(self.practitioner, prescription.prescription_id)
        self.assertTrue(body.startswith(b"%PDF"))

    def test_another_patient_cannot_download_the_prescription(self):
        prescription, _ = self.issue()
        with self.assertRaises(AuthorizationError):
            self.service.download(self.other_patient, prescription.prescription_id)

    def test_another_clinician_cannot_download_the_prescription(self):
        prescription, _ = self.issue()
        with self.assertRaises(AuthorizationError):
            self.service.download(self.other_practitioner, prescription.prescription_id)

    def test_downloading_is_audited_separately_from_reading(self):
        prescription, _ = self.issue()
        self.service.download(self.patient, prescription.prescription_id)
        actions = [entry.action for entry in self.audit.entries
                   if entry.resource_id == prescription.prescription_id]
        self.assertIn(ACTION_PRESCRIPTION_READ, actions)
        self.assertIn(ACTION_DOWNLOAD, actions)

    def test_a_refused_download_is_audited(self):
        prescription, _ = self.issue()
        with self.assertRaises(AuthorizationError):
            self.service.download(self.other_patient, prescription.prescription_id)
        denials = [entry for entry in self.audit.entries
                   if entry.action == ACTION_DOWNLOAD and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_a_tampered_document_is_not_served(self):
        import dataclasses
        prescription, document = self.issue()
        self.service.documents.put(dataclasses.replace(
            document, body=document.body + b"tampered"))
        with self.assertRaises(ValidationError):
            self.service.download(self.patient, prescription.prescription_id)
        errors = [entry for entry in self.audit.entries
                  if entry.action == ACTION_DOWNLOAD and entry.outcome == OUTCOME_ERROR]
        self.assertEqual(len(errors), 1)

    def test_a_prescription_without_a_document_cannot_be_downloaded(self):
        prescription, _ = self.issue()
        self.service.documents._documents.clear()
        self.service.documents._by_request.clear()
        with self.assertRaises(ValidationError):
            self.service.download(self.patient, prescription.prescription_id)


class LifecycleTest(PrescriptionTestCase):
    def test_the_prescriber_can_complete_a_prescription(self):
        prescription, _ = self.issue()
        completed = self.service.complete(self.practitioner, prescription.prescription_id)
        self.assertEqual(completed.status, STATUS_COMPLETED)

    def test_cancelling_needs_a_reason(self):
        prescription, _ = self.issue()
        with self.assertRaises(ValidationError):
            self.service.cancel(self.practitioner, prescription.prescription_id, reason="")

    def test_a_prescription_can_be_cancelled_with_a_reason(self):
        prescription, _ = self.issue()
        cancelled = self.service.cancel(self.practitioner, prescription.prescription_id,
                                         reason="the patient has an allergy")
        self.assertEqual(cancelled.status, STATUS_CANCELLED)

    def test_a_completed_prescription_is_final(self):
        prescription, _ = self.issue()
        self.service.complete(self.practitioner, prescription.prescription_id)
        with self.assertRaises(ValidationError):
            self.service.cancel(self.practitioner, prescription.prescription_id, reason="x")

    def test_a_patient_cannot_change_a_prescription(self):
        prescription, _ = self.issue()
        with self.assertRaises(AuthorizationError):
            self.service.change_status(self.patient, prescription.prescription_id,
                                       STATUS_CANCELLED, reason="not needed")

    def test_another_clinician_cannot_change_a_prescription(self):
        prescription, _ = self.issue()
        with self.assertRaises(AuthorizationError):
            self.service.change_status(self.other_practitioner, prescription.prescription_id,
                                       STATUS_CANCELLED, reason="not needed")

    def test_an_unknown_status_is_refused(self):
        prescription, _ = self.issue()
        with self.assertRaises(ValidationError):
            self.service.change_status(self.practitioner, prescription.prescription_id,
                                       "not-a-status")

    def test_a_status_change_is_audited(self):
        prescription, _ = self.issue()
        self.service.complete(self.practitioner, prescription.prescription_id)
        entries = [entry for entry in self.audit.entries
                   if entry.action == ACTION_STATUS_CHANGE]
        self.assertTrue(entries)
        self.assertTrue(any(entry.outcome == OUTCOME_SUCCESS for entry in entries))

    def test_a_refused_transition_is_audited(self):
        prescription, _ = self.issue()
        self.service.complete(self.practitioner, prescription.prescription_id)
        with self.assertRaises(ValidationError):
            self.service.cancel(self.practitioner, prescription.prescription_id, reason="x")
        denials = [entry for entry in self.audit.entries
                   if entry.action == ACTION_STATUS_CHANGE and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_an_issued_document_is_not_rewritten_by_a_status_change(self):
        prescription, document = self.issue()
        self.service.complete(self.practitioner, prescription.prescription_id)
        stored = self.service.documents.get_for_request(prescription.prescription_id)
        self.assertEqual(stored.body, document.body)
        self.assertIn(b"Status: active", stored.body)


if __name__ == "__main__":
    unittest.main()

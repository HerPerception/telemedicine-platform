"""Tests for the remediations of the OPS-001 review.

Each of these is a finding from `docs/reviews/compliance-review.md` that was
cheap and safe to close, and each has a test so that it cannot quietly come
back.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import unittest
from unittest import mock

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.errors import AuthenticationError
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.server import FhirApplication
from telemedicine.models import Role
from telemedicine.prescriptions import PrescriptionService
from telemedicine.records import PatientRecord, PractitionerRecord, RecordsService


class AccountEnumerationTest(unittest.TestCase):
    """Finding SEC-01: the login told an attacker which accounts exist."""

    def setUp(self):
        self.service = AuthService(audit=AuditLog(), password_iterations=1000)
        self.service.register("ada@example.org", "a-long-passphrase", Role.PATIENT,
                              record_id="patient-1")

    def test_an_unknown_account_still_spends_the_verification_time(self):
        # The verification is what makes the response slow; skipping it for an
        # unknown address is what made the difference measurable.
        with mock.patch("telemedicine.auth.verify_password", wraps=None) as verifier:
            verifier.return_value = False
            with self.assertRaises(AuthenticationError):
                self.service.authenticate("nobody@example.org", "a-long-passphrase")
        self.assertTrue(verifier.called,
                        "an unknown account must still run a password verification")

    def test_a_wrong_password_is_still_refused(self):
        with self.assertRaises(AuthenticationError):
            self.service.authenticate("ada@example.org", "not-the-passphrase")

    def test_the_two_failures_are_indistinguishable(self):
        with self.assertRaises(AuthenticationError) as unknown:
            self.service.authenticate("nobody@example.org", "a-long-passphrase")
        with self.assertRaises(AuthenticationError) as wrong:
            self.service.authenticate("ada@example.org", "not-the-passphrase")
        self.assertEqual(str(unknown.exception), str(wrong.exception))


class SessionInvalidationTest(unittest.TestCase):
    """Finding SEC-02: a password change left the old sessions alive."""

    def setUp(self):
        self.service = AuthService(audit=AuditLog(), password_iterations=1000)
        self.account = self.service.register("ada@example.org", "a-long-passphrase",
                                             Role.PATIENT, record_id="patient-1")

    def test_a_password_change_ends_the_sessions(self):
        token, _session = self.service.create_session(self.account)
        self.assertEqual(self.service.authenticate_session(token).user_id,
                         self.account.user_id)
        self.service.set_password(self.account, "a-long-passphrase", "a-new-long-passphrase")
        with self.assertRaises(AuthenticationError):
            self.service.authenticate_session(token)

    def test_a_new_session_still_works_after_the_change(self):
        self.service.set_password(self.account, "a-long-passphrase", "a-new-long-passphrase")
        token, _session = self.service.create_session(self.account)
        self.assertEqual(self.service.authenticate_session(token).user_id,
                         self.account.user_id)

    def test_the_change_is_audited_with_the_number_of_sessions_ended(self):
        self.service.create_session(self.account)
        self.service.set_password(self.account, "a-long-passphrase", "a-new-long-passphrase")
        entries = [entry for entry in self.service.audit.entries
                   if entry.action == "auth.password_change"]
        self.assertEqual(len(entries), 1)
        self.assertIn("session(s) revoked", entries[0].detail)


class ResponseHeaderTest(unittest.TestCase):
    """Finding PRIV-01: a patient's record could be cached by a proxy."""

    def setUp(self):
        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.booking = BookingService(self.slots, audit=self.audit, records=self.records)
        self.prescriptions = PrescriptionService(self.records, audit=self.audit)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.account = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.records.add_patient(PatientRecord(patient_id="patient-1",
                                               user_id=self.account.user_id,
                                               display_name="Ada Nwosu Okonkwo",
                                               mrn="MRN-000123"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id="user-practitioner",
            display_name="Dr. Elena Ramirez", identifier="1234567893",
            specialty="General Practice", license_number="MD-2019-4471"))
        self.application = FhirApplication(
            FhirRepository(self.records, self.booking, self.prescriptions), self.auth)

    def test_a_record_response_is_not_cacheable(self):
        token, _session = self.auth.create_session(self.account)
        response = self.application.handle(
            "GET", "/fhir/Patient/patient-1", {},
            {"Authorization": f"Bearer {token}"}, b"")
        self.assertEqual(response.status, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Pragma"], "no-cache")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_an_error_response_is_not_cacheable_either(self):
        response = self.application.handle("GET", "/fhir/Patient/patient-1", {}, {}, b"")
        self.assertEqual(response.status, 401)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_a_refusal_does_not_explain_itself(self):
        """Finding SEC-03: the reason a caller was refused was in the response."""
        other = self.auth.register("other@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-2")
        self.records.add_patient(PatientRecord(patient_id="patient-2", user_id=other.user_id,
                                               display_name="Someone Else",
                                               mrn="MRN-000124"))
        token, _session = self.auth.create_session(other)
        response = self.application.handle(
            "GET", "/fhir/Patient/patient-1", {},
            {"Authorization": f"Bearer {token}"}, b"")
        self.assertEqual(response.status, 403)
        body = json.loads(response.body.decode("utf-8"))
        diagnostics = body["issue"][0]["diagnostics"]
        self.assertNotIn("patient-1", diagnostics)
        self.assertNotIn("scope", diagnostics)
        self.assertNotIn("in scope", diagnostics)
        self.assertEqual(diagnostics, "not permitted: read on patient")

    def test_the_reason_is_still_in_the_audit_log(self):
        other = self.auth.register("other@example.org", "a-long-passphrase", Role.PATIENT,
                                   record_id="patient-2")
        self.records.add_patient(PatientRecord(patient_id="patient-2", user_id=other.user_id,
                                               display_name="Someone Else",
                                               mrn="MRN-000124"))
        token, _session = self.auth.create_session(other)
        self.application.handle("GET", "/fhir/Patient/patient-1", {},
                                {"Authorization": f"Bearer {token}"}, b"")
        denials = [entry for entry in self.audit.entries if entry.outcome == "denied"]
        self.assertTrue(denials)
        self.assertIn("denied", denials[0].detail)


if __name__ == "__main__":
    unittest.main()

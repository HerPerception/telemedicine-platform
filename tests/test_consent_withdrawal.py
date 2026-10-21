"""Tests for withdrawing a consent.

The task this answers was a question, not a feature: **can a patient take a
consent back, on their own, and does it take effect at once?**

Section 35 of the Nigeria Data Protection Act 2023 says a data subject has
the right to withdraw consent at any time, and that the controller must make
it "as easy for the data subject to withdraw, as to give consent". So:

* the patient withdraws **without a clinician**;
* the state says **withdrawn**, and the history keeps what was agreed and
  when it was taken back;
* **the next use of the record for that purpose is refused** — the gate is
  asked when the use happens, not when the consent was taken;
* the withdrawal is **audited**.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import unittest
from pathlib import Path

from telemedicine.consent import (
    OPTIONAL_PURPOSES,
    PURPOSE_CONSULTATION_RECORDING,
    PURPOSE_RESEARCH,
    ConsentRequiredError,
    ConsentService,
)
from telemedicine.errors import AuthorizationError

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTICE = "2026-10-21"


class TheWithdrawalTest(unittest.TestCase):
    """The endpoint, the state, the block and the audit."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.auth import AuthService
        from telemedicine.models import Role

        self.audit = AuditLog()
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.patient = self.auth.register("ada@example.org", "a-long-passphrase",
                                          Role.PATIENT, record_id="patient-1")
        self.clinician = self.auth.register("dr@example.org", "a-long-passphrase",
                                            Role.PRACTITIONER,
                                            record_id="practitioner-1")
        self.consents = ConsentService(audit=self.audit)

        from telemedicine.consent_api import ConsentEndpoints
        self.endpoints = ConsentEndpoints(self.consents)

    def request(self, method, path, account=None, body=None):
        """A request to the consent endpoints.

        The endpoints are given the path below ``/fhir/consent``, so the
        prefix is taken off here and the test can use the path a client
        would use.
        """
        remainder = path[len("/fhir/consent"):].strip("/")
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        return self.endpoints.handle(method, remainder, {}, account, payload)

    # -- 1. the endpoint exists, and works for the patient ----------------

    def test_the_patient_can_withdraw_without_a_clinician(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        status, payload = self.request("DELETE", "/fhir/consent/research",
                                       self.patient)
        self.assertEqual(status, 204)
        self.assertIsNone(payload)

    def test_the_withdrawal_may_also_be_asked_for_with_a_post(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        status, payload = self.request("POST", "/fhir/consent/research/withdraw",
                                       self.patient)
        self.assertEqual(status, 201)
        self.assertEqual(_purpose(payload, PURPOSE_RESEARCH)["state"], "withdrawn")

    def test_a_clinician_cannot_withdraw_on_the_patients_behalf(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        with self.assertRaises(AuthorizationError):
            self.request("DELETE", "/fhir/consent/research", self.clinician)

    def test_a_call_without_a_session_is_refused(self):
        with self.assertRaises(Exception):
            self.request("DELETE", "/fhir/consent/research")

    # -- 2. the state ------------------------------------------------------

    def test_the_state_says_withdrawn(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.request("DELETE", "/fhir/consent/research", self.patient)
        state = self.consents.state_for_actor(self.patient)
        self.assertEqual(_purpose(state, PURPOSE_RESEARCH)["state"], "withdrawn")

    def test_the_history_keeps_what_was_agreed(self):
        # The record is append-only: the grant is still there, and the
        # withdrawal is a second event, not a change to the first.
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.request("DELETE", "/fhir/consent/research", self.patient)
        events = self.consents.history(self.patient.user_id)
        self.assertEqual([event.kind for event in events], ["granted", "withdrawn"])

    def test_withdrawing_one_purpose_leaves_the_others(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.consents.grant(self.patient.user_id, "teaching", NOTICE)
        self.request("DELETE", "/fhir/consent/research", self.patient)
        state = self.consents.state_for_actor(self.patient)
        self.assertEqual(_purpose(state, PURPOSE_RESEARCH)["state"], "withdrawn")
        self.assertEqual(_purpose(state, "teaching")["state"], "granted")

    # -- 3. the use is blocked, at once ------------------------------------

    def test_the_gate_refuses_after_a_withdrawal(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.request("DELETE", "/fhir/consent/research", self.patient)
        with self.assertRaises(ConsentRequiredError) as caught:
            self.consents.require_consent(self.patient.user_id, PURPOSE_RESEARCH)
        self.assertIn("not consented", str(caught.exception))

    def test_the_gate_allows_while_the_consent_stands(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.consents.require_consent(self.patient.user_id, PURPOSE_RESEARCH)

    def test_a_use_that_was_already_started_is_not_the_gate_s_business(self):
        # The gate is asked when the use happens. A recording that was
        # already running when the patient withdrew is not stopped by it —
        # and pretending otherwise would be worse than saying so.
        self.consents.grant(self.patient.user_id, PURPOSE_CONSULTATION_RECORDING,
                            NOTICE)
        self.consents.require_consent(self.patient.user_id,
                                      PURPOSE_CONSULTATION_RECORDING)
        self.request("DELETE", "/fhir/consent/consultation_recording", self.patient)
        with self.assertRaises(ConsentRequiredError):
            self.consents.require_consent(self.patient.user_id,
                                          PURPOSE_CONSULTATION_RECORDING)

    def test_every_purpose_can_be_withdrawn(self):
        for purpose in OPTIONAL_PURPOSES:
            with self.subTest(purpose=purpose):
                self.consents.grant(self.patient.user_id, purpose, NOTICE)
                self.request("DELETE", f"/fhir/consent/{purpose}", self.patient)
                self.assertFalse(self.consents.has_consent(self.patient.user_id, purpose))

    # -- 4. the audit ------------------------------------------------------

    def test_the_withdrawal_is_audited(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        self.request("DELETE", "/fhir/consent/research", self.patient)
        entries = [entry for entry in self.audit.entries
                   if entry.action == "consent.withdrawn"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].actor_user_id, self.patient.user_id)
        self.assertEqual(entries[0].outcome, "success")

    def test_the_refusal_to_withdraw_someone_elses_is_audited(self):
        self.consents.grant(self.patient.user_id, PURPOSE_RESEARCH, NOTICE)
        with self.assertRaises(AuthorizationError):
            self.request("DELETE", "/fhir/consent/research", self.clinician)
        refusals = [entry for entry in self.audit.entries
                    if entry.action == "consent.changed" and entry.outcome == "denied"]
        self.assertTrue(refusals)


class TheRecordingIsBlockedTest(unittest.TestCase):
    """The one optional use that exists: the recording of a consultation."""

    def setUp(self):
        from telemedicine.audit import AuditLog
        from telemedicine.auth import AuthService
        from telemedicine.booking import BookingService, SlotService
        from telemedicine.models import Role
        from telemedicine.records import (
            PatientRecord,
            PractitionerRecord,
            RecordsService,
        )
        from telemedicine.video import MediaConfiguration, VideoService
        from telemedicine.video_api import VideoApplication

        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.booking = BookingService(self.slots, audit=self.audit,
                                      records=self.records)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)
        self.consents = ConsentService(audit=self.audit)
        self.service = VideoService(
            self.records, audit=self.audit,
            media=MediaConfiguration(host="video.example.ng",
                                     url="wss://video.example.ng",
                                     api_key="the-key", api_secret="the-secret",
                                     recording_enabled=True),
            consents=self.consents)
        self.application = VideoApplication(self.service, self.auth)

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
        self.slot = self.slots.create_slot(
            self.practitioner, practitioner_id="practitioner-1",
            local_start=_tomorrow_at(14), local_end=_tomorrow_at(14, 30),
            timezone_name="Europe/Berlin")
        self.appointment = self.booking.book(self.patient, self.slot.slot_id)

    def token(self):
        token, _session = self.auth.create_session(self.patient)
        return {"authorization": f"Bearer {token}"}

    def video_token(self):
        return self.application.handle(
            "POST", f"/video/consultations/{self.appointment.appointment_id}/video-token",
            {}, self.token(), b"")

    def test_a_recording_with_the_consent_is_allowed(self):
        self.consents.grant(self.patient.user_id, PURPOSE_CONSULTATION_RECORDING, NOTICE)
        response = self.video_token()
        self.assertEqual(response.status, 201)

    def test_a_recording_after_a_withdrawal_is_refused(self):
        self.consents.grant(self.patient.user_id, PURPOSE_CONSULTATION_RECORDING, NOTICE)
        self.assertEqual(self.video_token().status, 201)

        # The patient takes it back, on their own.
        # The patient takes it back, on their own, over HTTP.
        from telemedicine.consent_api import ConsentEndpoints
        endpoints = ConsentEndpoints(self.consents)
        status, _payload = endpoints.handle(
            "DELETE", "consultation_recording", {}, self.patient, b"")
        self.assertEqual(status, 204)

        # And the next attempt is refused.
        response = self.video_token()
        self.assertEqual(response.status, 403)
        self.assertIn("not consented",
                      json.loads(response.body.decode("utf-8"))["message"])


class ThePatientPageTest(unittest.TestCase):
    """The page the patient withdraws from."""

    @classmethod
    def setUpClass(cls):
        cls.text = (REPO_ROOT / "web" / "consents.html").read_text(encoding="utf-8")

    def test_the_page_exists(self):
        self.assertTrue((REPO_ROOT / "web" / "consents.html").is_file())

    def test_the_page_has_a_withdraw_button(self):
        self.assertIn("Withdraw consent", self.text)

    def test_the_page_reads_the_consents(self):
        self.assertIn("/fhir/consent", self.text)

    def test_the_page_withdraws_with_one_request(self):
        self.assertIn('method: "DELETE"', self.text)
        self.assertIn("/fhir/consent/", self.text)

    def test_the_page_says_the_withdrawal_takes_effect_at_once(self):
        self.assertIn("takes effect at once", self.text)


def _purpose(state, purpose):
    for entry in state["purposes"]:
        if entry["purpose"] == purpose:
            return entry
    raise AssertionError(f"no entry for '{purpose}'")


def _tomorrow_at(hour: int, minute: int = 0):
    from datetime import datetime, timedelta
    moment = datetime.now() + timedelta(days=1)
    return moment.replace(hour=hour, minute=minute, second=0, microsecond=0)


if __name__ == "__main__":
    unittest.main()

"""Tests for the consent endpoints.

The consent endpoints are what make section 35 of the Nigeria Data Protection
Act 2023 real: a data subject has the right to withdraw consent at any time,
and the controller has to make it "as easy for the data subject to withdraw,
as to give consent". So:

* granting a consent is one request, and withdrawing it is one request;
* a consent has to name the version of the notice the patient saw;
* a clinician who treats the patient may read the state — they have to know
  before they use a record for a research purpose — and may change nothing;
* nobody but the patient may read or change a patient's consents;
* everything that happens is audited.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.consent import OPTIONAL_PURPOSES
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.server import FhirApplication
from telemedicine.models import Role
from telemedicine.records import Appointment, PatientRecord, PractitionerRecord, RecordsService

NOTICE = "2026-10-21"
PATIENT_ID = "patient-1"
PRACTITIONER_ID = "practitioner-1"
OTHER_PRACTITIONER_ID = "practitioner-2"


class Clock:
    def __init__(self, start=None):
        self.now = start or datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class ConsentApiTestCase(unittest.TestCase):
    """An application with a patient, a clinician who treats them, and one who does not."""

    def setUp(self):
        self.clock = Clock()
        self.audit = AuditLog(clock=self.clock)
        self.auth = AuthService(audit=self.audit, password_iterations=1000,
                                clock=self.clock)
        self.records = RecordsService(audit=self.audit)

        self.patient_account = self.auth.register(
            "ada@example.org", "a-long-passphrase", Role.PATIENT, record_id=PATIENT_ID)
        self.practitioner_account = self.auth.register(
            "dr@example.org", "a-long-passphrase", Role.PRACTITIONER,
            record_id=PRACTITIONER_ID)
        self.other_account = self.auth.register(
            "other@example.org", "a-long-passphrase", Role.PRACTITIONER,
            record_id=OTHER_PRACTITIONER_ID)

        self.records.add_patient(PatientRecord(
            patient_id=PATIENT_ID,
            user_id=self.patient_account.user_id,
            display_name="Ada Nwosu",
            date_of_birth="1988-04-12",
            mrn="MRN-000123",
            family_name="Nwosu",
            given_names=("Ada",),
            gender="female",
        ))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id=PRACTITIONER_ID,
            user_id=self.practitioner_account.user_id,
            display_name="Dr Elena Ramirez",
            identifier="1234567893",
            specialty="General Practice",
            family_name="Ramirez",
            given_names=("Elena",),
            credentials=("MD",),
            gender="female",
        ))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id=OTHER_PRACTITIONER_ID,
            user_id=self.other_account.user_id,
            display_name="Dr Chidi Obi",
            identifier="9876543210",
            specialty="General Practice",
            family_name="Obi",
            given_names=("Chidi",),
            credentials=("MBBS",),
            gender="male",
        ))

        # The treatment relationship: the appointment is what makes the
        # clinician one of the clinicians who may see this patient's consents.
        now = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
        self.records.add_appointment(Appointment(
            appointment_id="appointment-1",
            patient_id=PATIENT_ID,
            practitioner_id=PRACTITIONER_ID,
            patient_user_id=self.patient_account.user_id,
            practitioner_user_id=self.practitioner_account.user_id,
            starts_at=now,
            ends_at=now + timedelta(minutes=30),
        ))

        from telemedicine.consent import ConsentService
        self.consents = ConsentService(audit=self.audit, clock=self.clock,
                                       records=self.records,
                                       authorizer=self.records.authorizer)
        self.application = FhirApplication(
            FhirRepository(self.records, None, None), self.auth, consent=self.consents)

    # -- helpers ------------------------------------------------------------

    def token_for(self, email):
        response = self.application.handle(
            "POST", "/fhir/session", {}, {},
            json.dumps({"email": email, "password": "a-long-passphrase"}).encode("utf-8"))
        self.assertEqual(response.status, 201)
        return json.loads(response.body.decode("utf-8"))["token"]

    def request(self, method, path, token=None, body=None, query=None):
        headers = {"authorization": f"Bearer {token}"} if token else {}
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        return self.application.handle(method, path, query or {}, headers, payload)

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))


class ThePatientsOwnConsentsTest(ConsentApiTestCase):
    def test_a_patient_sees_an_empty_state_to_begin_with(self):
        token = self.token_for("ada@example.org")
        response = self.request("GET", "/fhir/consent", token)
        self.assertEqual(response.status, 200)
        state = self.payload(response)
        self.assertFalse(state["notice_acknowledged"])
        self.assertIsNone(state["notice_version"])
        self.assertEqual([entry["purpose"] for entry in state["purposes"]],
                         list(OPTIONAL_PURPOSES))

    def test_every_optional_purpose_is_described(self):
        token = self.token_for("ada@example.org")
        state = self.payload(self.request("GET", "/fhir/consent", token))
        for entry in state["purposes"]:
            self.assertTrue(entry["description"])
            self.assertEqual(entry["state"], "not_granted")

    def test_the_notice_can_be_acknowledged(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/notice", token,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 201)
        state = self.payload(response)
        self.assertTrue(state["notice_acknowledged"])
        self.assertEqual(state["notice_version"], NOTICE)

    def test_the_notice_needs_a_version(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/notice", token, {})
        self.assertEqual(response.status, 400)

    def test_a_consent_can_be_granted(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/research", token,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 201)
        state = self.payload(response)
        research = _purpose(state, "research")
        self.assertEqual(research["state"], "granted")
        self.assertEqual(research["notice_version"], NOTICE)

    def test_a_consent_needs_the_version_of_the_notice(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/research", token, {})
        self.assertEqual(response.status, 400)
        self.assertIn("notice_version", self.payload(response)["issue"][0]["diagnostics"])

    def test_the_method_and_the_evidence_are_recorded(self):
        token = self.token_for("ada@example.org")
        self.request("POST", "/fhir/consent/teaching", token,
                     {"notice_version": NOTICE, "method": "in person",
                      "evidence": "signed form 4"})
        events = self.consents.history(self.patient_account.user_id)
        grant = [event for event in events if event.kind == "granted"][0]
        self.assertEqual(grant.method, "in person")
        self.assertEqual(grant.evidence, "signed form 4")

    def test_an_unknown_purpose_is_not_found(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/selling_the_data", token,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 404)

    def test_the_clinical_record_cannot_be_consented_to(self):
        token = self.token_for("ada@example.org")
        response = self.request("POST", "/fhir/consent/treatment", token,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 404)
        self.assertIn("S.30(1)(g)", self.payload(response)["issue"][0]["diagnostics"])

    def test_a_consent_can_be_withdrawn(self):
        token = self.token_for("ada@example.org")
        self.request("POST", "/fhir/consent/research", token,
                     {"notice_version": NOTICE})
        response = self.request("DELETE", "/fhir/consent/research", token)
        self.assertEqual(response.status, 204)
        self.assertEqual(response.body, b"")

        state = self.payload(self.request("GET", "/fhir/consent", token))
        self.assertEqual(_purpose(state, "research")["state"], "withdrawn")

    def test_withdrawing_is_as_easy_as_granting(self):
        # One request each. Section 35 says it has to be.
        token = self.token_for("ada@example.org")
        granted = self.request("POST", "/fhir/consent/marketing", token,
                               {"notice_version": NOTICE})
        withdrawn = self.request("DELETE", "/fhir/consent/marketing", token)
        self.assertEqual(granted.status, 201)
        self.assertEqual(withdrawn.status, 204)

    def test_withdrawing_one_purpose_leaves_the_others(self):
        token = self.token_for("ada@example.org")
        self.request("POST", "/fhir/consent/research", token, {"notice_version": NOTICE})
        self.request("POST", "/fhir/consent/teaching", token, {"notice_version": NOTICE})
        self.request("DELETE", "/fhir/consent/research", token)
        state = self.payload(self.request("GET", "/fhir/consent", token))
        self.assertEqual(_purpose(state, "research")["state"], "withdrawn")
        self.assertEqual(_purpose(state, "teaching")["state"], "granted")

    def test_the_response_is_not_cacheable(self):
        token = self.token_for("ada@example.org")
        response = self.request("GET", "/fhir/consent", token)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_the_state_carries_no_patient_data(self):
        token = self.token_for("ada@example.org")
        response = self.request("GET", "/fhir/consent", token)
        body = response.body.decode("utf-8")
        self.assertNotIn("MRN", body)
        self.assertNotIn("Ada", body)


class AuthenticationTest(ConsentApiTestCase):
    def test_the_state_needs_a_session(self):
        self.assertEqual(self.request("GET", "/fhir/consent").status, 401)

    def test_granting_needs_a_session(self):
        response = self.request("POST", "/fhir/consent/research", None,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 401)

    def test_withdrawing_needs_a_session(self):
        self.assertEqual(self.request("DELETE", "/fhir/consent/research").status, 401)

    def test_a_bad_token_is_refused(self):
        response = self.request("GET", "/fhir/consent", "not-a-token")
        self.assertEqual(response.status, 401)


class TheCliniciansViewTest(ConsentApiTestCase):
    def test_a_clinician_who_treats_the_patient_may_read_the_state(self):
        token = self.token_for("dr@example.org")
        self.request("POST", "/fhir/consent/research",
                     self.token_for("ada@example.org"), {"notice_version": NOTICE})
        response = self.request("GET", "/fhir/consent", token,
                                query={"patient": [PATIENT_ID]})
        self.assertEqual(response.status, 200)
        state = self.payload(response)
        self.assertEqual(_purpose(state, "research")["state"], "granted")

    def test_a_clinician_who_does_not_treat_the_patient_may_not(self):
        token = self.token_for("other@example.org")
        response = self.request("GET", "/fhir/consent", token,
                                query={"patient": [PATIENT_ID]})
        self.assertEqual(response.status, 403)

    def test_a_patient_may_not_read_another_patients_consents(self):
        token = self.token_for("ada@example.org")
        response = self.request("GET", "/fhir/consent", token,
                                query={"patient": ["patient-someone-else"]})
        self.assertEqual(response.status, 403)

    def test_a_clinician_may_not_grant_a_consent_for_the_patient(self):
        token = self.token_for("dr@example.org")
        response = self.request("POST", "/fhir/consent/research", token,
                                {"notice_version": NOTICE})
        self.assertEqual(response.status, 403)

    def test_a_clinician_may_not_withdraw_a_consent_for_the_patient(self):
        token = self.token_for("dr@example.org")
        response = self.request("DELETE", "/fhir/consent/research", token)
        self.assertEqual(response.status, 403)

    def test_a_clinician_reading_the_state_is_audited(self):
        token = self.token_for("dr@example.org")
        self.request("GET", "/fhir/consent", token, query={"patient": [PATIENT_ID]})
        views = [entry for entry in self.audit.entries if entry.action == "consent.viewed"]
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].actor_user_id, self.practitioner_account.user_id)
        self.assertEqual(views[0].resource_type, "consent")


class TheAuditTrailTest(ConsentApiTestCase):
    def test_every_change_is_audited(self):
        token = self.token_for("ada@example.org")
        self.request("POST", "/fhir/consent/notice", token, {"notice_version": NOTICE})
        self.request("POST", "/fhir/consent/research", token, {"notice_version": NOTICE})
        self.request("DELETE", "/fhir/consent/research", token)
        actions = [entry.action for entry in self.audit.entries
                   if entry.action.startswith("consent.")]
        self.assertEqual(actions, ["consent.notice_acknowledged",
                                   "consent.granted",
                                   "consent.withdrawn"])

    def test_a_refused_change_is_audited_as_refused(self):
        token = self.token_for("dr@example.org")
        self.request("POST", "/fhir/consent/research", token, {"notice_version": NOTICE})
        refusals = [entry for entry in self.audit.entries
                    if entry.action.startswith("consent.") and entry.outcome == "denied"]
        self.assertTrue(refusals)
        self.assertEqual(refusals[0].actor_user_id, self.practitioner_account.user_id)


class TheRuleTableTest(unittest.TestCase):
    """The rules themselves, without the API."""

    def test_a_patient_may_read_and_change_their_own_consents(self):
        from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
        from telemedicine.models import UserAccount
        authorizer = Authorizer()
        patient = UserAccount(user_id="user-patient", email="ada@example.org",
                              role=Role.PATIENT, password_hash="x", record_id="patient-1")
        scope = AccessScope(owner_user_id="user-patient")
        self.assertTrue(authorizer.decide(patient, Action.READ,
                                          ResourceType.CONSENT, scope).allowed)
        self.assertTrue(authorizer.decide(patient, Action.UPDATE,
                                          ResourceType.CONSENT, scope).allowed)

    def test_a_patient_may_not_read_another_patients_consents(self):
        from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
        from telemedicine.models import UserAccount
        authorizer = Authorizer()
        patient = UserAccount(user_id="user-patient", email="ada@example.org",
                              role=Role.PATIENT, password_hash="x", record_id="patient-1")
        scope = AccessScope(owner_user_id="user-someone-else")
        self.assertFalse(authorizer.decide(patient, Action.READ,
                                           ResourceType.CONSENT, scope).allowed)

    def test_a_practitioner_may_read_but_not_change(self):
        from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
        from telemedicine.models import UserAccount
        authorizer = Authorizer()
        practitioner = UserAccount(user_id="user-practitioner", email="dr@example.org",
                                   role=Role.PRACTITIONER, password_hash="x",
                                   record_id="practitioner-1")
        scope = AccessScope(owner_user_id="user-patient",
                            treating_user_ids=frozenset({"user-practitioner"}))
        self.assertTrue(authorizer.decide(practitioner, Action.READ,
                                          ResourceType.CONSENT, scope).allowed)
        self.assertFalse(authorizer.decide(practitioner, Action.UPDATE,
                                           ResourceType.CONSENT, scope).allowed)


def _purpose(state, purpose):
    for entry in state["purposes"]:
        if entry["purpose"] == purpose:
            return entry
    raise AssertionError(f"no entry for '{purpose}'")

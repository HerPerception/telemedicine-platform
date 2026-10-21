"""Tests for the FHIR R4 API.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from telemedicine.audit import AuditLog
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.server import FhirApplication, make_server
from telemedicine.fhir.validation import validate_resource
from telemedicine.models import Role
from telemedicine.prescriptions import PrescriptionService
from telemedicine.records import (
    Encounter,
    PatientRecord,
    PractitionerRecord,
    RecordsService,
)

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)


class ApiTestCase(unittest.TestCase):
    """A small system with a patient, a practitioner, a visit and a prescription."""

    def setUp(self):
        self.audit = AuditLog()
        self.records = RecordsService(audit=self.audit)
        self.slots = SlotService(audit=self.audit)
        self.booking = BookingService(self.slots, audit=self.audit, records=self.records)
        self.prescriptions = PrescriptionService(self.records, audit=self.audit)
        self.auth = AuthService(audit=self.audit, password_iterations=1000)

        self.patient_account = self.auth.register(
            "ada@example.org", "a-long-passphrase", Role.PATIENT, record_id="patient-1")
        self.practitioner_account = self.auth.register(
            "dr@example.org", "a-long-passphrase", Role.PRACTITIONER,
            record_id="practitioner-1")
        self.other_patient_account = self.auth.register(
            "other@example.org", "a-long-passphrase", Role.PATIENT, record_id="patient-2")
        self.other_practitioner_account = self.auth.register(
            "other-dr@example.org", "a-long-passphrase", Role.PRACTITIONER,
            record_id="practitioner-2")

        self.records.add_patient(PatientRecord(
            patient_id="patient-1", user_id=self.patient_account.user_id,
            display_name="Ada Nwosu Okonkwo", mrn="MRN-000123",
            family_name="Okonkwo", given_names=("Ada", "Nwosu")))
        self.records.add_patient(PatientRecord(
            patient_id="patient-2", user_id=self.other_patient_account.user_id,
            display_name="Someone Else", mrn="MRN-000124"))
        self.records.add_practitioner(PractitionerRecord(
            practitioner_id="practitioner-1", user_id=self.practitioner_account.user_id,
            display_name="Dr. Elena Ramirez", identifier="1234567893",
            specialty="General Practice", license_number="MD-2019-4471"))

        # A booked visit, the encounter it produced and a prescription.
        self.slot = self.slots.create_slot(
            self.practitioner_account, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 21, 14, 0), local_end=datetime(2026, 10, 21, 14, 30),
            timezone_name="Europe/Berlin")
        self.appointment = self.booking.book(self.patient_account, self.slot.slot_id)
        self.encounter = self.records.create_encounter(
            self.practitioner_account, self.appointment.appointment_id,
            started_at=NOW, ended_at=NOW + timedelta(minutes=25),
            chief_complaint="Persistent cough", clinical_note="Reviewed home management.")
        self.prescription, self.document = self.prescriptions.issue(
            self.practitioner_account, self.encounter.encounter_id,
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            brand_name="Emoclox",
            generic_name="Amoxicillin 500mg",
            strength="500mg Capsules",
            nafdac_number="A4-1234",
            dosage_text="Take one capsule by mouth three times a day for 5 days.")

        self.repository = FhirRepository(self.records, self.booking, self.prescriptions)
        self.application = FhirApplication(self.repository, self.auth)

    # -- helpers -----------------------------------------------------------

    def token_for(self, account) -> str:
        token, _session = self.auth.create_session(account)
        return token

    def call(self, method: str, path: str, token: str = None, body=None,
             base: str = "/fhir"):
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/fhir+json"
        return self.application.handle(method, base + path, {}, headers, data or b"")

    def payload(self, response):
        return json.loads(response.body.decode("utf-8"))


class AuthenticationTest(ApiTestCase):
    def test_the_metadata_endpoint_is_public(self):
        response = self.call("GET", "/metadata")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["resourceType"], "CapabilityStatement")

    def test_a_request_without_a_token_is_refused(self):
        response = self.call("GET", "/Patient/patient-1")
        self.assertEqual(response.status, 401)
        self.assertIn("WWW-Authenticate", response.headers)
        self.assertEqual(self.payload(response)["resourceType"], "OperationOutcome")

    def test_a_request_with_a_bad_token_is_refused(self):
        response = self.call("GET", "/Patient/patient-1", token="not-a-token")
        self.assertEqual(response.status, 401)

    def test_a_revoked_token_is_refused(self):
        token = self.token_for(self.patient_account)
        self.auth.revoke_session(token)
        response = self.call("GET", "/Patient/patient-1", token=token)
        self.assertEqual(response.status, 401)


class ReadTest(ApiTestCase):
    def test_a_patient_reads_their_own_record(self):
        response = self.call("GET", "/Patient/patient-1", token=self.token_for(self.patient_account))
        self.assertEqual(response.status, 200)
        resource = self.payload(response)
        self.assertEqual(resource["resourceType"], "Patient")
        self.assertEqual(resource["id"], "patient-1")
        self.assertEqual(resource["identifier"][0]["value"], "MRN-000123")
        self.assertEqual(validate_resource(resource, source="Patient"), [])

    def test_a_patient_cannot_read_another_patients_record(self):
        response = self.call("GET", "/Patient/patient-2",
                             token=self.token_for(self.patient_account))
        self.assertEqual(response.status, 403)
        self.assertEqual(self.payload(response)["issue"][0]["code"], "forbidden")

    def test_a_practitioner_reads_a_patient_they_treat(self):
        response = self.call("GET", "/Patient/patient-1",
                             token=self.token_for(self.practitioner_account))
        self.assertEqual(response.status, 200)

    def test_a_practitioner_cannot_read_an_unrelated_patient(self):
        response = self.call("GET", "/Patient/patient-2",
                             token=self.token_for(self.other_practitioner_account))
        self.assertEqual(response.status, 403)

    def test_an_unknown_id_is_not_found(self):
        response = self.call("GET", "/Patient/patient-nobody",
                             token=self.token_for(self.patient_account))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.payload(response)["issue"][0]["code"], "not-found")

    def test_an_unknown_resource_type_is_not_found(self):
        response = self.call("GET", "/Organization/x", token=self.token_for(self.patient_account))
        self.assertEqual(response.status, 404)

    def test_the_appointment_is_readable_by_both_parties(self):
        for account in (self.patient_account, self.practitioner_account):
            with self.subTest(role=account.role):
                response = self.call("GET", f"/Appointment/{self.appointment.appointment_id}",
                                     token=self.token_for(account))
                self.assertEqual(response.status, 200)
                resource = self.payload(response)
                self.assertEqual(resource["resourceType"], "Appointment")
                self.assertEqual(len(resource["participant"]), 2)
                self.assertEqual(validate_resource(resource, source="Appointment"), [])

    def test_the_encounter_and_the_prescription_are_readable(self):
        patient_token = self.token_for(self.patient_account)
        response = self.call("GET", f"/Encounter/{self.encounter.encounter_id}",
                             token=patient_token)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["class"]["code"], "AMB")

        response = self.call("GET", f"/MedicationRequest/{self.prescription.prescription_id}",
                             token=patient_token)
        self.assertEqual(response.status, 200)
        resource = self.payload(response)
        self.assertEqual(resource["medicationCodeableConcept"]["coding"][0]["code"],
                         "AMOX-500-CAP")
        self.assertEqual(validate_resource(resource, source="MedicationRequest"), [])

    def test_another_patient_cannot_read_the_prescription(self):
        response = self.call("GET", f"/MedicationRequest/{self.prescription.prescription_id}",
                             token=self.token_for(self.other_patient_account))
        self.assertEqual(response.status, 403)

    def test_search_returns_a_bundle(self):
        response = self.call("GET", "/Patient", token=self.token_for(self.practitioner_account))
        self.assertEqual(response.status, 200)
        bundle = self.payload(response)
        self.assertEqual(bundle["resourceType"], "Bundle")
        self.assertEqual(bundle["type"], "searchset")
        self.assertEqual(bundle["total"], 1)
        self.assertEqual(bundle["entry"][0]["resource"]["id"], "patient-1")

    def test_a_patient_searches_only_themselves(self):
        response = self.call("GET", "/Patient", token=self.token_for(self.patient_account))
        bundle = self.payload(response)
        self.assertEqual(bundle["total"], 1)
        self.assertEqual(bundle["entry"][0]["resource"]["id"], "patient-1")

    def test_the_prescription_search_returns_the_patients_own(self):
        response = self.call("GET", "/MedicationRequest",
                             token=self.token_for(self.patient_account))
        bundle = self.payload(response)
        self.assertEqual(bundle["total"], 1)


class WriteTest(ApiTestCase):
    def test_a_patient_updates_their_own_record(self):
        token = self.token_for(self.patient_account)
        body = {
            "resourceType": "Patient",
            "id": "patient-1",
            "name": [{"use": "official", "family": "Okonkwo-Nwosu", "given": ["Ada"]}],
            "telecom": [{"system": "phone", "value": "+1-555-0199"}],
            "gender": "female",
        }
        response = self.call("PUT", "/Patient/patient-1", token=token, body=body)
        self.assertEqual(response.status, 200)
        resource = self.payload(response)
        self.assertEqual(resource["name"][0]["family"], "Okonkwo-Nwosu")
        self.assertEqual(resource["gender"], "female")
        self.assertEqual(validate_resource(resource, source="Patient"), [])

    def test_a_patient_cannot_update_another_patient(self):
        response = self.call("PUT", "/Patient/patient-2",
                             token=self.token_for(self.patient_account),
                             body={"resourceType": "Patient", "id": "patient-2",
                                   "gender": "male"})
        self.assertEqual(response.status, 403)

    def test_a_patient_books_an_appointment(self):
        slot = self.slots.create_slot(
            self.practitioner_account, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 22, 9, 0),
            local_end=datetime(2026, 10, 22, 9, 30), timezone_name="Europe/Berlin")
        body = {
            "resourceType": "Appointment",
            "status": "booked",
            "slot": [{"reference": f"Slot/{slot.slot_id}"}],
            "participant": [
                {"actor": {"reference": "Patient/patient-1"}, "status": "accepted"},
                {"actor": {"reference": "Practitioner/practitioner-1"}, "status": "accepted"},
            ],
        }
        response = self.call("POST", "/Appointment", token=self.token_for(self.patient_account),
                             body=body)
        self.assertEqual(response.status, 201)
        resource = self.payload(response)
        self.assertEqual(resource["resourceType"], "Appointment")
        self.assertIn("Location", response.headers)
        self.assertEqual(validate_resource(resource, source="Appointment"), [])

    def test_booking_a_slot_twice_is_a_conflict(self):
        slot = self.slots.create_slot(
            self.practitioner_account, practitioner_id="practitioner-1",
            local_start=datetime(2026, 10, 22, 10, 0),
            local_end=datetime(2026, 10, 22, 10, 30), timezone_name="Europe/Berlin")
        body = {
            "resourceType": "Appointment",
            "status": "booked",
            "slot": [{"reference": f"Slot/{slot.slot_id}"}],
            "participant": [
                {"actor": {"reference": "Patient/patient-1"}, "status": "accepted"},
            ],
        }
        token = self.token_for(self.patient_account)
        first = self.call("POST", "/Appointment", token=token, body=body)
        self.assertEqual(first.status, 201)
        second = self.call("POST", "/Appointment", token=token, body=body)
        self.assertEqual(second.status, 409)
        self.assertEqual(self.payload(second)["issue"][0]["code"], "conflict")

    def test_a_patient_cannot_issue_a_prescription(self):
        body = {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {
                "coding": [{
                    "system": "https://telemedicine.example.org/CodeSystem/medication",
                    "code": "AMOX-500-CAP", "display": "Amoxicillin 500 mg capsule"},
                    {"system": "https://www.nafdac.gov.ng/registration",
                     "code": "A4-1234", "display": "Emoclox 500mg Capsules"}],
                "text": "Emoclox [Amoxicillin 500mg] - NAFDAC: A4-1234"},
            "extension": [
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-brand-name", "valueString": "Emoclox"},
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-generic-name", "valueString": "Amoxicillin 500mg"},
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-strength", "valueString": "500mg Capsules"}],
            "subject": {"reference": "Patient/patient-1"},
            "encounter": {"reference": f"Encounter/{self.encounter.encounter_id}"},
            "requester": {"reference": "Practitioner/practitioner-1"},
            "dosageInstruction": [{"text": "One capsule three times a day."}],
        }
        response = self.call("POST", "/MedicationRequest",
                             token=self.token_for(self.patient_account), body=body)
        self.assertEqual(response.status, 403)

    def test_the_treating_clinician_issues_a_prescription(self):
        body = {
            "resourceType": "MedicationRequest",
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {
                "coding": [{
                    "system": "https://telemedicine.example.org/CodeSystem/medication",
                    "code": "AMOX-500-CAP", "display": "Amoxicillin 500 mg capsule"},
                    {"system": "https://www.nafdac.gov.ng/registration",
                     "code": "A4-1234", "display": "Emoclox 500mg Capsules"}],
                "text": "Emoclox [Amoxicillin 500mg] - NAFDAC: A4-1234"},
            "extension": [
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-brand-name", "valueString": "Emoclox"},
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-generic-name", "valueString": "Amoxicillin 500mg"},
                {"url": "https://telemedicine.example.org/fhir/StructureDefinition/"
                        "medication-strength", "valueString": "500mg Capsules"}],
            "subject": {"reference": "Patient/patient-1"},
            "encounter": {"reference": f"Encounter/{self.encounter.encounter_id}"},
            "requester": {"reference": "Practitioner/practitioner-1"},
            "dosageInstruction": [{"text": "One capsule three times a day."}],
        }
        response = self.call("POST", "/MedicationRequest",
                             token=self.token_for(self.practitioner_account), body=body)
        self.assertEqual(response.status, 201)
        resource = self.payload(response)
        self.assertEqual(validate_resource(resource, source="MedicationRequest"), [])

    def test_a_prescription_is_cancelled_through_the_api(self):
        body = {
            "resourceType": "MedicationRequest",
            "id": self.prescription.prescription_id,
            "status": "cancelled",
            "statusReason": {"text": "the patient has an allergy"},
        }
        response = self.call("PUT", f"/MedicationRequest/{self.prescription.prescription_id}",
                             token=self.token_for(self.practitioner_account), body=body)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.payload(response)["status"], "cancelled")

    def test_cancelling_without_a_reason_is_rejected(self):
        body = {
            "resourceType": "MedicationRequest",
            "id": self.prescription.prescription_id,
            "status": "cancelled",
        }
        response = self.call("PUT", f"/MedicationRequest/{self.prescription.prescription_id}",
                             token=self.token_for(self.practitioner_account), body=body)
        self.assertEqual(response.status, 400)

    def test_a_clinical_record_is_never_deleted(self):
        response = self.call("DELETE", f"/Patient/patient-1",
                             token=self.token_for(self.patient_account))
        self.assertEqual(response.status, 405)
        self.assertEqual(self.payload(response)["issue"][0]["code"], "not-supported")

    def test_a_malformed_body_is_rejected(self):
        response = self.application.handle(
            "PUT", "/fhir/Patient/patient-1", {},
            {"Authorization": f"Bearer {self.token_for(self.patient_account)}"},
            b"{not json")
        self.assertEqual(response.status, 400)

    def test_a_body_of_the_wrong_type_is_rejected(self):
        response = self.call("PUT", "/Patient/patient-1",
                             token=self.token_for(self.patient_account),
                             body={"resourceType": "Practitioner", "id": "practitioner-1"})
        self.assertEqual(response.status, 400)

    def test_an_unsupported_method_is_reported(self):
        response = self.call("POST", "/Patient/patient-1",
                             token=self.token_for(self.patient_account), body={})
        self.assertEqual(response.status, 405)


class AuditTest(ApiTestCase):
    def test_reading_through_the_api_is_audited(self):
        token = self.token_for(self.patient_account)
        self.call("GET", "/Patient/patient-1", token=token)
        entries = [entry for entry in self.audit.entries
                   if entry.action == "record.read" and entry.resource_id == "patient-1"]
        self.assertTrue(entries)

    def test_a_refused_read_is_audited(self):
        self.call("GET", "/Patient/patient-2", token=self.token_for(self.patient_account))
        denials = [entry for entry in self.audit.entries if entry.outcome == "denied"]
        self.assertTrue(denials)


class HttpTest(ApiTestCase):
    """The same thing over a real socket."""

    def setUp(self):
        super().setUp()
        self.server = make_server(self.application, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path, token=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8")), response.headers
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8")), error.headers

    def test_a_read_over_http(self):
        status, body, headers = self.get("/fhir/Patient/patient-1",
                                          self.token_for(self.patient_account))
        self.assertEqual(status, 200)
        self.assertEqual(body["resourceType"], "Patient")
        self.assertIn("application/fhir+json", headers["Content-Type"])

    def test_an_unauthenticated_read_over_http(self):
        status, body, _headers = self.get("/fhir/Patient/patient-1")
        self.assertEqual(status, 401)
        self.assertEqual(body["resourceType"], "OperationOutcome")

    def test_the_metadata_over_http(self):
        status, body, _headers = self.get("/fhir/metadata")
        self.assertEqual(status, 200)
        self.assertEqual(body["fhirVersion"], "4.0.1")


if __name__ == "__main__":
    unittest.main()

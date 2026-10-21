"""Tests for the FHIR API: the mapping, and the resources it produces.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.fhir import serialization
from telemedicine.fhir.validation import validate_resource
from telemedicine.records import (
    Appointment,
    Encounter,
    PatientRecord,
    PractitionerRecord,
    Prescription,
)

NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)


def patient_record():
    return PatientRecord(
        patient_id="patient-1",
        user_id="user-patient",
        display_name="Ada Nwosu Okonkwo",
        date_of_birth="1988-04-12",
        mrn="MRN-000123",
        family_name="Okonkwo",
        given_names=("Ada", "Nwosu"),
        gender="unknown",
        phone="+1-555-0100",
        email="ada.okonkwo@example.com",
        address_line=("12 Harbour Street", "Apartment 3B"),
        address_city="Boston",
        address_region="MA",
        address_postal_code="02110",
        address_country="US",
    )


def practitioner_record():
    return PractitionerRecord(
        practitioner_id="practitioner-1",
        user_id="user-practitioner",
        display_name="Dr. Elena Ramirez",
        identifier="1234567893",
        specialty="General Practice",
        family_name="Ramirez",
        given_names=("Elena",),
        credentials=("MD",),
        gender="female",
        license_number="MD-2019-4471",
        license_region="Massachusetts Board of Registration in Medicine",
    )


def appointment_record():
    return Appointment(
        appointment_id="appointment-1",
        patient_id="patient-1",
        practitioner_id="practitioner-1",
        patient_user_id="user-patient",
        practitioner_user_id="user-practitioner",
        starts_at=NOW,
        ends_at=NOW + timedelta(minutes=30),
        status="booked",
        slot_id="slot-1",
        reason_text="Follow-up for persistent cough",
        patient_note="Please join five minutes early.",
        created_at=NOW - timedelta(days=1),
    )


def encounter_record():
    return Encounter(
        encounter_id="encounter-1",
        appointment_id="appointment-1",
        patient_id="patient-1",
        practitioner_id="practitioner-1",
        patient_user_id="user-patient",
        practitioner_user_id="user-practitioner",
        status="finished",
        started_at=NOW,
        ended_at=NOW + timedelta(minutes=25),
        chief_complaint="Persistent cough, six days",
        clinical_note="Reviewed home management and safety-netting advice.",
    )


def prescription_record():
    return Prescription(
        prescription_id="prescription-1",
        encounter_id="encounter-1",
        patient_id="patient-1",
        prescriber_id="practitioner-1",
        patient_user_id="user-patient",
        prescriber_user_id="user-practitioner",
        medication_system="https://telemedicine.example.org/CodeSystem/medication",
        medication_code="AMOX-500-CAP",
        medication_display="Amoxicillin 500 mg capsule",
        brand_name="Emoclox",
        generic_name="Amoxicillin 500mg",
        strength="500mg Capsules",
        nafdac_number="A4-1234",
        dosage_text="Take one capsule by mouth three times a day for 5 days.",
        status="active",
        authored_on=NOW,
        notes="Take with food.",
        refills=0,
        dispense_quantity=15,
        route_text="Oral",
        dose_quantity=1,
        dose_unit="capsule",
        duration_days=5,
    )


class SerializationTest(unittest.TestCase):
    def test_every_resource_satisfies_the_published_profile(self):
        resources = {
            "Patient": serialization.patient_resource(patient_record()),
            "Practitioner": serialization.practitioner_resource(practitioner_record()),
            "Appointment": serialization.appointment_resource(appointment_record()),
            "Encounter": serialization.encounter_resource(encounter_record()),
            "MedicationRequest": serialization.medication_request_resource(prescription_record()),
        }
        for name, resource in resources.items():
            with self.subTest(resource=name):
                self.assertEqual(validate_resource(resource, source=name), [])

    def test_the_patient_carries_the_declared_identifier_and_name(self):
        resource = serialization.patient_resource(patient_record())
        self.assertEqual(resource["resourceType"], "Patient")
        self.assertEqual(resource["id"], "patient-1")
        identifier = resource["identifier"][0]
        self.assertEqual(identifier["system"],
                         "https://telemedicine.example.org/identifier/mrn")
        self.assertEqual(identifier["value"], "MRN-000123")
        self.assertEqual(resource["name"][0]["family"], "Okonkwo")
        self.assertEqual(resource["name"][0]["given"], ["Ada", "Nwosu"])
        self.assertEqual(resource["gender"], "unknown")
        self.assertEqual(resource["birthDate"], "1988-04-12")
        self.assertEqual([t["system"] for t in resource["telecom"]], ["phone", "email"])
        self.assertEqual(resource["address"][0]["city"], "Boston")
        self.assertEqual(resource["address"][0]["state"], "MA")

    def test_the_practitioner_carries_the_npi_and_the_qualification(self):
        resource = serialization.practitioner_resource(practitioner_record())
        self.assertEqual(resource["identifier"][0]["system"], "http://hl7.org/fhir/sid/us-npi")
        self.assertEqual(resource["identifier"][0]["value"], "1234567893")
        self.assertEqual(resource["name"][0]["suffix"], ["MD"])
        qualification = resource["qualification"][0]
        self.assertEqual(qualification["identifier"][0]["value"], "MD-2019-4471")
        self.assertEqual(qualification["code"]["text"], "General Practice")
        self.assertIn("Massachusetts", qualification["issuer"]["display"])

    def test_the_appointment_carries_both_participants(self):
        resource = serialization.appointment_resource(appointment_record())
        self.assertEqual(resource["status"], "booked")
        self.assertEqual(resource["start"], "2026-10-21T14:00:00Z")
        self.assertEqual(resource["end"], "2026-10-21T14:30:00Z")
        self.assertEqual(resource["minutesDuration"], 30)
        self.assertEqual(resource["slot"][0]["reference"], "Slot/slot-1")
        self.assertEqual(resource["reasonCode"][0]["text"], "Follow-up for persistent cough")
        self.assertEqual(resource["comment"], "Please join five minutes early.")
        types = [p["type"][0]["coding"][0]["code"] for p in resource["participant"]]
        self.assertEqual(types, ["SBJ", "PPR"])
        actors = [p["actor"]["reference"] for p in resource["participant"]]
        self.assertEqual(actors, ["Patient/patient-1", "Practitioner/practitioner-1"])

    def test_the_encounter_carries_the_class_the_subject_and_the_note(self):
        resource = serialization.encounter_resource(encounter_record())
        self.assertEqual(resource["status"], "finished")
        self.assertEqual(resource["class"]["code"], "AMB")
        self.assertEqual(resource["type"][0]["coding"][0]["code"], "VR")
        self.assertEqual(resource["subject"]["reference"], "Patient/patient-1")
        self.assertEqual(resource["appointment"][0]["reference"], "Appointment/appointment-1")
        extension = resource["extension"][0]
        self.assertTrue(extension["url"].endswith("/encounter-clinical-note"))
        self.assertIn("safety-netting", extension["valueString"])

    def test_the_prescription_carries_the_medication_and_the_dosage(self):
        resource = serialization.medication_request_resource(prescription_record())
        self.assertEqual(resource["status"], "active")
        self.assertEqual(resource["intent"], "order")
        coding = resource["medicationCodeableConcept"]["coding"][0]
        self.assertEqual(coding["code"], "AMOX-500-CAP")
        self.assertEqual(coding["system"],
                         "https://telemedicine.example.org/CodeSystem/medication")
        self.assertEqual(resource["subject"]["reference"], "Patient/patient-1")
        self.assertEqual(resource["encounter"]["reference"], "Encounter/encounter-1")
        self.assertEqual(resource["requester"]["reference"], "Practitioner/practitioner-1")
        dosage = resource["dosageInstruction"][0]
        self.assertIn("one capsule by mouth", dosage["text"])
        self.assertEqual(dosage["route"]["text"], "Oral")
        self.assertEqual(dosage["doseAndRate"][0]["doseQuantity"]["value"], 1)
        self.assertEqual(dosage["timing"]["repeat"]["boundsDuration"]["value"], 5)
        self.assertEqual(resource["dispenseRequest"]["numberOfRepeatsAllowed"], 0)
        self.assertEqual(resource["dispenseRequest"]["quantity"]["value"], 15)
        self.assertEqual(resource["note"][0]["text"], "Take with food.")

    def test_the_prescription_carries_the_nigerian_dispensing_identity(self):
        """ENG-016: two codings, the text, and the extensions."""
        resource = serialization.medication_request_resource(prescription_record())
        concept = resource["medicationCodeableConcept"]

        # The coded concept comes first, so a client that reads the first
        # coding reads what it read before.
        self.assertEqual(concept["coding"][0]["code"], "AMOX-500-CAP")

        # The registration number comes second.
        nafdac = concept["coding"][1]
        self.assertEqual(nafdac["system"], "https://www.nafdac.gov.ng/registration")
        self.assertEqual(nafdac["code"], "A4-1234")
        self.assertEqual(nafdac["display"], "Emoclox 500mg Capsules")

        # The text says all three things.
        self.assertEqual(concept["text"],
                         "Emoclox [Amoxicillin 500mg] - NAFDAC: A4-1234")

        # And the structured values are carried as extensions.
        extensions = {extension["url"]: extension["valueString"]
                      for extension in resource["extension"]}
        self.assertEqual(extensions[
            "https://telemedicine.example.org/fhir/StructureDefinition/medication-brand-name"],
            "Emoclox")
        self.assertEqual(extensions[
            "https://telemedicine.example.org/fhir/StructureDefinition/medication-generic-name"],
            "Amoxicillin 500mg")
        self.assertEqual(extensions[
            "https://telemedicine.example.org/fhir/StructureDefinition/medication-strength"],
            "500mg Capsules")

    def test_a_prescription_from_before_the_requirement_still_reads(self):
        """The resource of a row that has no brand or number is still valid."""
        import dataclasses
        legacy = dataclasses.replace(prescription_record(), brand_name="",
                                     generic_name="", nafdac_number="")
        resource = serialization.medication_request_resource(legacy)
        concept = resource["medicationCodeableConcept"]
        self.assertEqual(len(concept["coding"]), 1)
        self.assertEqual(concept["text"], "Amoxicillin 500 mg capsule")
        self.assertEqual(validate_resource(resource, source="MedicationRequest"), [])

    def test_the_operation_outcome_has_the_shape_fhir_expects(self):
        outcome = serialization.operation_outcome("error", "forbidden", "not for you")
        self.assertEqual(outcome["resourceType"], "OperationOutcome")
        issue = outcome["issue"][0]
        self.assertEqual(issue["severity"], "error")
        self.assertEqual(issue["code"], "forbidden")
        self.assertEqual(issue["diagnostics"], "not for you")

    def test_the_capability_statement_declares_r4(self):
        statement = serialization.capability_statement()
        self.assertEqual(statement["resourceType"], "CapabilityStatement")
        self.assertEqual(statement["fhirVersion"], "4.0.1")
        resources = {entry["type"] for entry in statement["rest"][0]["resource"]}
        self.assertEqual(resources, {"Patient", "Practitioner", "Appointment", "Encounter",
                                     "MedicationRequest"})


if __name__ == "__main__":
    unittest.main()

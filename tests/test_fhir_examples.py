"""Tests for the ENG-001 FHIR R4 example resources and the validator.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import copy
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import validate_fhir_examples as v  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "docs" / "fhir" / "examples"


def load(name):
    with (EXAMPLES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class ExampleResourcesTest(unittest.TestCase):
    """The shipped examples must satisfy the mapping the project declares."""

    def test_all_examples_are_valid(self):
        errors, resources = v.validate_directory(EXAMPLES_DIR)
        self.assertEqual(errors, [], f"example resources failed validation: {errors}")
        self.assertEqual(len(resources), 7)

    def test_every_example_is_known(self):
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            with self.subTest(path=path.name):
                resource = load(path.name)
                self.assertIn(resource["resourceType"], v.PROFILES)

    def test_ids_are_fhir_compatible(self):
        for path in sorted(EXAMPLES_DIR.glob("*.json")):
            with self.subTest(path=path.name):
                self.assertRegex(load(path.name)["id"], r"^[A-Za-z0-9\-.]{1,64}$")

    def test_cross_references_resolve(self):
        index = v.build_example_index(v.load_examples(EXAMPLES_DIR))
        self.assertIn("Patient", index)
        self.assertIn("Practitioner", index)
        self.assertIn("Appointment", index)
        self.assertIn("Encounter", index)
        self.assertIn("MedicationRequest", index)
        self.assertIn("Slot", index)
        self.assertIn("Schedule", index)

    def test_appointment_links_the_visit_chain(self):
        appointment = load("appointment.json")
        self.assertEqual(appointment["status"], "booked")
        self.assertEqual(appointment["minutesDuration"], 30)
        self.assertEqual(len(appointment["participant"]), 2)
        self.assertEqual(appointment["slot"][0]["reference"],
                         "Slot/5d8e9f0a-6b7c-4d4e-8f5a-6b7c8d9e0f1a")

    def test_encounter_carries_the_declared_extension(self):
        encounter = load("encounter.json")
        urls = [extension["url"] for extension in encounter["extension"]]
        self.assertIn(
            "https://telemedicine.example.org/fhir/StructureDefinition/encounter-clinical-note",
            urls,
        )

    def test_prescription_is_tied_to_the_encounter_and_prescriber(self):
        prescription = load("medicationrequest.json")
        self.assertTrue(prescription["encounter"]["reference"].startswith("Encounter/"))
        self.assertTrue(prescription["requester"]["reference"].startswith("Practitioner/"))
        self.assertTrue(prescription["subject"]["reference"].startswith("Patient/"))
        self.assertEqual(prescription["intent"], "order")
        self.assertEqual(prescription["status"], "active")


class ValidatorBehaviourTest(unittest.TestCase):
    """The validator must actually catch the mistakes it claims to catch."""

    def setUp(self):
        self.resources = v.load_examples(EXAMPLES_DIR)
        self.index = v.build_example_index(self.resources)

    def errors_for(self, resource, name="test.json"):
        return v.validate_resource(resource, self.index, name)

    def test_valid_resource_has_no_errors(self):
        self.assertEqual(self.errors_for(copy.deepcopy(load("appointment.json"))), [])

    def test_missing_required_element_is_reported(self):
        resource = copy.deepcopy(load("appointment.json"))
        del resource["status"]
        self.assertTrue(any("'status' is required" in error for error in self.errors_for(resource)))

    def test_unknown_element_is_reported(self):
        resource = copy.deepcopy(load("patient.json"))
        resource["nickname"] = "Ada"
        self.assertTrue(any("'nickname' is not part of the R4 Patient" in error
                            for error in self.errors_for(resource)))

    def test_code_outside_the_value_set_is_reported(self):
        resource = copy.deepcopy(load("appointment.json"))
        resource["status"] = "definitely-not-a-status"
        self.assertTrue(any("is not in the declared value set" in error
                            for error in self.errors_for(resource)))

    def test_gender_must_use_the_declared_code_system(self):
        resource = copy.deepcopy(load("patient.json"))
        resource["gender"] = "not-a-gender"
        self.assertTrue(any("is not in the declared value set" in error
                            for error in self.errors_for(resource)))

    def test_missing_gender_is_reported(self):
        resource = copy.deepcopy(load("patient.json"))
        del resource["gender"]
        self.assertTrue(any("gender" in error for error in self.errors_for(resource)))

    def test_dangling_reference_is_reported(self):
        resource = copy.deepcopy(load("appointment.json"))
        resource["participant"][0]["actor"]["reference"] = "Patient/does-not-exist"
        self.assertTrue(any("does not resolve" in error for error in self.errors_for(resource)))

    def test_malformed_reference_is_reported(self):
        resource = copy.deepcopy(load("encounter.json"))
        resource["subject"]["reference"] = "not a reference"
        self.assertTrue(any("is not a valid FHIR reference" in error
                            for error in self.errors_for(resource)))

    def test_bad_instant_is_reported(self):
        resource = copy.deepcopy(load("appointment.json"))
        resource["start"] = "2026-10-21 14:00:00"
        self.assertTrue(any("is not a valid instant" in error for error in self.errors_for(resource)))

    def test_end_before_start_is_reported(self):
        resource = copy.deepcopy(load("appointment.json"))
        resource["end"] = "2026-10-21T13:00:00Z"
        self.assertTrue(any("is not after start" in error for error in self.errors_for(resource)))

    def test_undeclared_extension_is_reported(self):
        resource = copy.deepcopy(load("encounter.json"))
        resource["extension"][0]["url"] = "https://example.org/StructureDefinition/unknown"
        self.assertTrue(any("is not declared by the mapping" in error
                            for error in self.errors_for(resource)))

    def test_appointment_participant_requires_status(self):
        resource = copy.deepcopy(load("appointment.json"))
        del resource["participant"][0]["status"]
        self.assertTrue(any("ParticipationStatus" in error for error in self.errors_for(resource)))

    def test_encounter_participant_does_not_require_status(self):
        resource = copy.deepcopy(load("encounter.json"))
        self.assertEqual(self.errors_for(resource), [])

    def test_prescription_requires_a_medication(self):
        resource = copy.deepcopy(load("medicationrequest.json"))
        del resource["medicationCodeableConcept"]
        self.assertTrue(any("medication[x] is required" in error
                            for error in self.errors_for(resource)))

    def test_profile_required_element_is_reported(self):
        resource = copy.deepcopy(load("patient.json"))
        del resource["name"]
        self.assertTrue(any("required by the telemedicine profile" in error
                            for error in self.errors_for(resource)))

    def test_unknown_resource_type_is_reported(self):
        resource = copy.deepcopy(load("patient.json"))
        resource["resourceType"] = "Organization"
        self.assertTrue(any("not one of the modelled resources" in error
                            for error in self.errors_for(resource)))

    def test_slot_status_must_be_known(self):
        resource = copy.deepcopy(load("slot.json"))
        resource["status"] = "maybe"
        self.assertTrue(any("is not in the declared value set" in error
                            for error in self.errors_for(resource)))


class ProfileTableTest(unittest.TestCase):
    """Guard the R4 element tables against accidental edits."""

    def test_choice_elements_are_expanded(self):
        self.assertIn("medicationCodeableConcept", v.CHOICE_VARIANTS["medication[x]"])
        self.assertIn("deceasedBoolean", v.CHOICE_VARIANTS["deceased[x]"])

    def test_required_elements_match_r4(self):
        self.assertEqual(v.PROFILES["Appointment"]["required"], ["participant", "status"])
        self.assertEqual(v.PROFILES["Encounter"]["required"], ["class", "status"])
        self.assertEqual(v.PROFILES["Slot"]["required"],
                         ["end", "schedule", "start", "status"])
        self.assertIn("medication[x]", v.PROFILES["MedicationRequest"]["required"])

    def test_value_sets_come_from_the_r4_code_systems(self):
        self.assertIn("booked", v.APPOINTMENT_STATUS["http://hl7.org/fhir/appointmentstatus"])
        self.assertIn("finished", v.ENCOUNTER_STATUS["http://hl7.org/fhir/encounter-status"])
        self.assertIn("order",
                      v.MEDICATION_REQUEST_INTENT[
                          "http://hl7.org/fhir/CodeSystem/medicationrequest-intent"])
        self.assertIn("AMB",
                      v.ENCOUNTER_CLASS[
                          "http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode"])


if __name__ == "__main__":
    unittest.main()

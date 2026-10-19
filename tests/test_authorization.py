"""Tests for role-scoped authorization over the clinical records.

Run from the repository root:

    python3 -m unittest discover -s tests -v
"""

import unittest
from datetime import datetime, timedelta, timezone

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.auth import AuthService
from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
from telemedicine.errors import AuthorizationError
from telemedicine.models import Role, UserAccount
from telemedicine.records import (
    ACTION_PRESCRIPTION_CREATE,
    ACTION_PRESCRIPTION_READ,
    Appointment,
    Encounter,
    PatientRecord,
    RecordsService,
)

PATIENT_ID = "patient-1"
OTHER_PATIENT_ID = "patient-2"
PRACTITIONER_ID = "practitioner-1"
OTHER_PRACTITIONER_ID = "practitioner-2"


def make_account(user_id, role, record_id):
    return UserAccount(
        user_id=user_id,
        email=f"{user_id}@example.org",
        role=role,
        password_hash="pbkdf2_sha256$1000$abc$def",
        record_id=record_id,
    )


class AuthorizationRulesTest(unittest.TestCase):
    """The rule table itself, independent of the service layer."""

    def setUp(self):
        self.authorizer = Authorizer()
        self.patient = make_account("user-patient", Role.PATIENT, PATIENT_ID)
        self.practitioner = make_account("user-practitioner", Role.PRACTITIONER, PRACTITIONER_ID)

    def test_a_patient_may_read_their_own_record(self):
        scope = AccessScope(owner_user_id="user-patient")
        self.assertTrue(self.authorizer.decide(self.patient, Action.READ, ResourceType.PATIENT,
                                                scope).allowed)

    def test_a_patient_may_not_read_another_patients_record(self):
        scope = AccessScope(owner_user_id="user-someone-else")
        decision = self.authorizer.decide(self.patient, Action.READ, ResourceType.PATIENT, scope)
        self.assertFalse(decision.allowed)

    def test_a_patient_may_not_issue_a_prescription(self):
        scope = AccessScope(owner_user_id="user-patient",
                            treating_user_ids=frozenset({"user-patient"}))
        decision = self.authorizer.decide(self.patient, Action.CREATE,
                                          ResourceType.MEDICATION_REQUEST, scope)
        self.assertFalse(decision.allowed)

    def test_a_practitioner_may_read_a_patient_they_treat(self):
        scope = AccessScope(owner_user_id="user-patient",
                            treating_user_ids=frozenset({"user-practitioner"}))
        self.assertTrue(self.authorizer.decide(self.practitioner, Action.READ,
                                                ResourceType.PATIENT, scope).allowed)

    def test_a_practitioner_may_not_read_an_unrelated_patient(self):
        scope = AccessScope(owner_user_id="user-patient",
                            treating_user_ids=frozenset({"user-other-practitioner"}))
        self.assertFalse(self.authorizer.decide(self.practitioner, Action.READ,
                                                 ResourceType.PATIENT, scope).allowed)

    def test_only_the_treating_clinician_may_issue_a_prescription(self):
        scope = AccessScope(owner_user_id="user-patient",
                            treating_user_ids=frozenset({"user-practitioner"}))
        self.assertTrue(self.authorizer.decide(self.practitioner, Action.CREATE,
                                                ResourceType.MEDICATION_REQUEST, scope).allowed)
        other = make_account("user-other-practitioner", Role.PRACTITIONER, OTHER_PRACTITIONER_ID)
        self.assertFalse(self.authorizer.decide(other, Action.CREATE,
                                                 ResourceType.MEDICATION_REQUEST, scope).allowed)

    def test_an_unknown_role_action_pair_is_denied(self):
        scope = AccessScope(owner_user_id="user-patient")
        decision = self.authorizer.decide(self.patient, Action.DELETE, ResourceType.PATIENT,
                                          scope)
        self.assertFalse(decision.allowed)
        self.assertIsNone(decision.rule)

    def test_a_disabled_account_is_denied_everything(self):
        disabled = UserAccount(
            user_id="user-patient",
            email="user-patient@example.org",
            role=Role.PATIENT,
            password_hash="pbkdf2_sha256$1000$abc$def",
            record_id=PATIENT_ID,
            disabled=True,
        )
        scope = AccessScope(owner_user_id="user-patient")
        self.assertFalse(self.authorizer.decide(disabled, Action.READ, ResourceType.PATIENT,
                                                scope).allowed)

    def test_require_raises_with_the_resource_details(self):
        scope = AccessScope(owner_user_id="user-someone-else")
        with self.assertRaises(AuthorizationError) as caught:
            self.authorizer.require(self.patient, Action.READ, ResourceType.PATIENT, scope,
                                    resource_id=PATIENT_ID)
        self.assertEqual(caught.exception.resource_id, PATIENT_ID)
        self.assertEqual(caught.exception.resource_type, "patient")
        self.assertEqual(caught.exception.action, "read")


class RecordsServiceAccessTest(unittest.TestCase):
    """The service layer: authorization plus the audit entry for each access."""

    def setUp(self):
        self.audit = AuditLog()
        self.service = RecordsService(audit=self.audit)

        self.patient = make_account("user-patient", Role.PATIENT, PATIENT_ID)
        self.other_patient = make_account("user-other-patient", Role.PATIENT, OTHER_PATIENT_ID)
        self.practitioner = make_account("user-practitioner", Role.PRACTITIONER,
                                         PRACTITIONER_ID)
        self.other_practitioner = make_account("user-other-practitioner", Role.PRACTITIONER,
                                               OTHER_PRACTITIONER_ID)

        self.service.add_patient(PatientRecord(patient_id=PATIENT_ID,
                                               user_id="user-patient",
                                               display_name="Ada Okonkwo"))
        self.service.add_patient(PatientRecord(patient_id=OTHER_PATIENT_ID,
                                               user_id="user-other-patient",
                                               display_name="Someone Else"))

        now = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)
        self.service.add_appointment(Appointment(
            appointment_id="appointment-1",
            patient_id=PATIENT_ID,
            practitioner_id=PRACTITIONER_ID,
            patient_user_id="user-patient",
            practitioner_user_id="user-practitioner",
            starts_at=now,
            ends_at=now + timedelta(minutes=30),
        ))
        self.service.add_encounter(Encounter(
            encounter_id="encounter-1",
            appointment_id="appointment-1",
            patient_id=PATIENT_ID,
            practitioner_id=PRACTITIONER_ID,
            patient_user_id="user-patient",
            practitioner_user_id="user-practitioner",
            started_at=now,
            ended_at=now + timedelta(minutes=25),
        ))

    # -- patient access ---------------------------------------------------

    def test_a_patient_may_read_their_own_record(self):
        record = self.service.read_patient_record(self.patient, PATIENT_ID)
        self.assertEqual(record.patient_id, PATIENT_ID)
        successes = [entry for entry in self.audit.entries
                     if entry.resource_type == "patient" and entry.outcome == OUTCOME_SUCCESS]
        self.assertEqual(len(successes), 1)
        self.assertEqual(successes[0].actor_user_id, "user-patient")

    def test_a_patient_may_not_read_another_patients_record(self):
        with self.assertRaises(AuthorizationError):
            self.service.read_patient_record(self.patient, OTHER_PATIENT_ID)
        denials = [entry for entry in self.audit.entries
                   if entry.resource_type == "patient" and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)
        self.assertEqual(denials[0].actor_user_id, "user-patient")

    def test_a_patient_may_read_their_own_encounter(self):
        encounter = self.service.read_encounter(self.patient, "encounter-1")
        self.assertEqual(encounter.encounter_id, "encounter-1")

    def test_a_patient_may_not_read_someone_elses_encounter(self):
        with self.assertRaises(AuthorizationError):
            self.service.read_encounter(self.other_patient, "encounter-1")

    # -- practitioner access ----------------------------------------------

    def test_a_practitioner_may_read_the_record_of_a_patient_they_treat(self):
        record = self.service.read_patient_record(self.practitioner, PATIENT_ID)
        self.assertEqual(record.patient_id, PATIENT_ID)

    def test_a_practitioner_may_not_read_an_unrelated_patient(self):
        with self.assertRaises(AuthorizationError):
            self.service.read_patient_record(self.other_practitioner, PATIENT_ID)

    def test_a_practitioner_may_read_the_appointment_they_treat(self):
        appointment = self.service.read_appointment(self.practitioner, "appointment-1")
        self.assertEqual(appointment.appointment_id, "appointment-1")

    # -- prescriptions -----------------------------------------------------

    def test_the_treating_clinician_may_issue_a_prescription(self):
        prescription = self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        self.assertEqual(prescription.patient_id, PATIENT_ID)
        self.assertEqual(prescription.prescriber_id, PRACTITIONER_ID)
        self.assertEqual(prescription.encounter_id, "encounter-1")
        creates = [entry for entry in self.audit.entries
                   if entry.action == ACTION_PRESCRIPTION_CREATE]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0].outcome, OUTCOME_SUCCESS)

    def test_another_clinician_may_not_issue_for_an_encounter_they_did_not_have(self):
        with self.assertRaises(AuthorizationError):
            self.service.issue_prescription(
                self.other_practitioner, "encounter-1",
                medication_code="AMOX-500-CAP",
                medication_display="Amoxicillin 500 mg capsule",
                dosage_text="One capsule by mouth three times a day for 5 days.",
            )
        denials = [entry for entry in self.audit.entries
                   if entry.action == ACTION_PRESCRIPTION_CREATE
                   and entry.outcome == OUTCOME_DENIED]
        self.assertEqual(len(denials), 1)

    def test_a_patient_may_not_issue_a_prescription(self):
        with self.assertRaises(AuthorizationError):
            self.service.issue_prescription(
                self.patient, "encounter-1",
                medication_code="AMOX-500-CAP",
                medication_display="Amoxicillin 500 mg capsule",
                dosage_text="One capsule by mouth three times a day for 5 days.",
            )

    def test_a_prescription_needs_a_medication_and_dosage(self):
        from telemedicine.errors import ValidationError
        with self.assertRaises(ValidationError):
            self.service.issue_prescription(self.practitioner, "encounter-1",
                                            medication_code="",
                                            medication_display="",
                                            dosage_text="")

    def test_the_patient_may_read_their_own_prescription(self):
        prescription = self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        read = self.service.read_prescription(self.patient, prescription.prescription_id)
        self.assertEqual(read.prescription_id, prescription.prescription_id)
        reads = [entry for entry in self.audit.entries
                 if entry.action == ACTION_PRESCRIPTION_READ]
        self.assertTrue(reads)

    def test_another_patient_may_not_read_a_prescription(self):
        prescription = self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        with self.assertRaises(AuthorizationError):
            self.service.read_prescription(self.other_patient, prescription.prescription_id)

    def test_the_prescriber_may_read_the_prescription_they_issued(self):
        prescription = self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        read = self.service.read_prescription(self.practitioner, prescription.prescription_id)
        self.assertEqual(read.prescription_id, prescription.prescription_id)

    def test_an_unrelated_clinician_may_not_read_the_prescription(self):
        prescription = self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        with self.assertRaises(AuthorizationError):
            self.service.read_prescription(self.other_practitioner, prescription.prescription_id)

    def test_prescription_creation_is_audited_against_the_encounter(self):
        self.service.issue_prescription(
            self.practitioner, "encounter-1",
            medication_code="AMOX-500-CAP",
            medication_display="Amoxicillin 500 mg capsule",
            dosage_text="One capsule by mouth three times a day for 5 days.",
        )
        entry = [item for item in self.audit.entries
                 if item.action == ACTION_PRESCRIPTION_CREATE][0]
        self.assertEqual(entry.resource_type, "medication_request")
        self.assertEqual(entry.resource_id, "encounter-1")
        self.assertEqual(entry.actor_user_id, "user-practitioner")

    def test_every_read_of_a_record_leaves_an_audit_entry(self):
        self.service.read_patient_record(self.patient, PATIENT_ID)
        self.service.read_encounter(self.practitioner, "encounter-1")
        actions = [entry.action for entry in self.audit.entries]
        self.assertEqual(actions.count("record.read"), 2)


if __name__ == "__main__":
    unittest.main()

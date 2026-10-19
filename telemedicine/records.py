"""The service layer that enforces authorization and writes the audit trail.

Every read of a clinical record and every prescription operation goes through
this service. It does two things for each call:

1. asks the :class:`~telemedicine.authorization.Authorizer` whether the
   caller may do what they are asking for, with the scope of that particular
   record; and
2. writes an audit entry — with the outcome, whether allowed or denied.

The clinical records here mirror the tables in ``db/schema.sql`` (ENG-001).
They are held in memory because there is no database yet; the identifiers and
relationships match the schema, including the ``account_ref`` link between an
account and the patient or practitioner row it belongs to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Tuple

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.models import Role, UserAccount

MEDICATION_CATALOG_SYSTEM = "https://telemedicine.example.org/CodeSystem/medication"

# Audit actions.
ACTION_RECORD_READ = "record.read"
ACTION_PRESCRIPTION_CREATE = "prescription.create"
ACTION_PRESCRIPTION_READ = "prescription.read"


@dataclass(frozen=True)
class PatientRecord:
    patient_id: str
    user_id: str
    display_name: str
    date_of_birth: Optional[str] = None


@dataclass(frozen=True)
class Appointment:
    appointment_id: str
    patient_id: str
    practitioner_id: str
    patient_user_id: str
    practitioner_user_id: str
    starts_at: datetime
    ends_at: datetime
    status: str = "booked"


@dataclass(frozen=True)
class Encounter:
    encounter_id: str
    appointment_id: str
    patient_id: str
    practitioner_id: str
    patient_user_id: str
    practitioner_user_id: str
    status: str = "in-progress"
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None


@dataclass(frozen=True)
class Prescription:
    prescription_id: str
    encounter_id: str
    patient_id: str
    prescriber_id: str
    patient_user_id: str
    prescriber_user_id: str
    medication_system: str
    medication_code: str
    medication_display: str
    dosage_text: str
    status: str = "active"
    authored_on: Optional[datetime] = None


class RecordsService:
    """Reads clinical records and issues prescriptions, with audit and scoping."""

    def __init__(self, authorizer: Optional[Authorizer] = None,
                 audit: Optional[AuditLog] = None):
        self.authorizer = authorizer if authorizer is not None else Authorizer()
        self.audit = audit if audit is not None else AuditLog()
        self._patients: Dict[str, PatientRecord] = {}
        self._appointments: Dict[str, Appointment] = {}
        self._encounters: Dict[str, Encounter] = {}
        self._prescriptions: Dict[str, Prescription] = {}

    # -- registration of clinical data ------------------------------------
    # These mirror the write paths of the application. They exist so that the
    # access-control rules can be exercised; they are not authorization
    # boundaries themselves and must not be exposed over the API.

    def add_patient(self, patient: PatientRecord) -> PatientRecord:
        self._patients[patient.patient_id] = patient
        return patient

    def add_appointment(self, appointment: Appointment) -> Appointment:
        self._appointments[appointment.appointment_id] = appointment
        return appointment

    def add_encounter(self, encounter: Encounter) -> Encounter:
        self._encounters[encounter.encounter_id] = encounter
        return encounter

    # -- lookups used to build the access scope ---------------------------

    def _treating_user_ids_for_patient(self, patient_id: str) -> FrozenSet[str]:
        """The clinicians who have an appointment or an encounter with a patient.

        This is the treatment relationship the authorization rules rely on. It
        is derived from the data, never from a flag that someone can forget
        to set.
        """
        treating = set()
        for appointment in self._appointments.values():
            if appointment.patient_id == patient_id:
                treating.add(appointment.practitioner_user_id)
        for encounter in self._encounters.values():
            if encounter.patient_id == patient_id:
                treating.add(encounter.practitioner_user_id)
        return frozenset(treating)

    def _patient_scope(self, patient: PatientRecord) -> AccessScope:
        return AccessScope(
            owner_user_id=patient.user_id,
            treating_user_ids=self._treating_user_ids_for_patient(patient.patient_id),
        )

    def _appointment_scope(self, appointment: Appointment) -> AccessScope:
        return AccessScope(
            owner_user_id=appointment.patient_user_id,
            treating_user_ids=frozenset({appointment.practitioner_user_id}),
        )

    def _encounter_scope(self, encounter: Encounter) -> AccessScope:
        return AccessScope(
            owner_user_id=encounter.patient_user_id,
            treating_user_ids=frozenset({encounter.practitioner_user_id}),
        )

    def _prescription_scope(self, prescription: Prescription) -> AccessScope:
        return AccessScope(
            owner_user_id=prescription.patient_user_id,
            treating_user_ids=frozenset({prescription.prescriber_user_id}),
            issued_by_user_id=prescription.prescriber_user_id,
        )

    # -- the audited access paths -----------------------------------------

    def read_patient_record(self, actor: UserAccount, patient_id: str) -> PatientRecord:
        """Read a patient record. The patient, or a clinician who treats them."""
        patient = self._require_patient(patient_id)
        scope = self._patient_scope(patient)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.PATIENT, scope, patient_id,
            audit_action=ACTION_RECORD_READ, detail=f"read patient record {patient_id}",
        )
        return patient

    def read_appointment(self, actor: UserAccount, appointment_id: str) -> Appointment:
        appointment = self._appointments.get(appointment_id)
        if appointment is None:
            raise ValidationError(f"no appointment with id '{appointment_id}'")
        scope = self._appointment_scope(appointment)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.APPOINTMENT, scope, appointment_id,
            audit_action=ACTION_RECORD_READ, detail=f"read appointment {appointment_id}",
        )
        return appointment

    def read_encounter(self, actor: UserAccount, encounter_id: str) -> Encounter:
        encounter = self._encounters.get(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        scope = self._encounter_scope(encounter)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.ENCOUNTER, scope, encounter_id,
            audit_action=ACTION_RECORD_READ, detail=f"read encounter {encounter_id}",
        )
        return encounter

    def issue_prescription(self, actor: UserAccount, encounter_id: str, *,
                           medication_code: str, medication_display: str,
                           dosage_text: str,
                           authored_on: Optional[datetime] = None) -> Prescription:
        """Issue a prescription against an encounter.

        Only the clinician who treated the encounter may issue it, and the
        prescription inherits the encounter's patient and prescriber — the
        same pairing the database enforces with a composite foreign key.
        """
        encounter = self._encounters.get(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        if not medication_code or not medication_display or not dosage_text:
            raise ValidationError(
                "a prescription needs a medication code, a display name and dosage text")
        scope = self._encounter_scope(encounter)
        self._authorize_and_audit(
            actor, Action.CREATE, ResourceType.MEDICATION_REQUEST, scope, encounter_id,
            audit_action=ACTION_PRESCRIPTION_CREATE,
            detail=f"issue prescription for encounter {encounter_id}",
        )
        prescription = Prescription(
            prescription_id=str(uuid.uuid4()),
            encounter_id=encounter.encounter_id,
            patient_id=encounter.patient_id,
            prescriber_id=encounter.practitioner_id,
            patient_user_id=encounter.patient_user_id,
            prescriber_user_id=encounter.practitioner_user_id,
            medication_system=MEDICATION_CATALOG_SYSTEM,
            medication_code=medication_code,
            medication_display=medication_display,
            dosage_text=dosage_text,
            authored_on=authored_on or datetime.now(timezone.utc),
        )
        self._prescriptions[prescription.prescription_id] = prescription
        return prescription

    def read_prescription(self, actor: UserAccount, prescription_id: str) -> Prescription:
        """Read a prescription. The patient it is for, or the clinician who issued it."""
        prescription = self._prescriptions.get(prescription_id)
        if prescription is None:
            raise ValidationError(f"no prescription with id '{prescription_id}'")
        scope = self._prescription_scope(prescription)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.MEDICATION_REQUEST, scope, prescription_id,
            audit_action=ACTION_PRESCRIPTION_READ, detail=f"read prescription {prescription_id}",
        )
        return prescription

    def list_prescriptions_for_encounter(self, actor: UserAccount,
                                         encounter_id: str) -> List[Prescription]:
        """The prescriptions issued against an encounter, with one audit entry."""
        encounter = self._encounters.get(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        scope = self._encounter_scope(encounter)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.MEDICATION_REQUEST, scope, encounter_id,
            audit_action=ACTION_PRESCRIPTION_READ,
            detail=f"list prescriptions for encounter {encounter_id}",
        )
        return [prescription for prescription in self._prescriptions.values()
                if prescription.encounter_id == encounter_id]

    # -- internals --------------------------------------------------------

    def _require_patient(self, patient_id: str) -> PatientRecord:
        patient = self._patients.get(patient_id)
        if patient is None:
            raise ValidationError(f"no patient with id '{patient_id}'")
        return patient

    def _authorize_and_audit(self, actor: UserAccount, action: Action,
                              resource_type: ResourceType, scope: AccessScope,
                              resource_id: str, *, audit_action: str, detail: str) -> None:
        """Authorize, then audit the outcome, then raise if it was refused."""
        decision = self.authorizer.decide(actor, action, resource_type, scope)
        if decision.allowed:
            self.audit.append(
                actor_user_id=actor.user_id,
                actor_role=actor.role.value,
                action=audit_action,
                resource_type=resource_type.value,
                resource_id=resource_id,
                outcome=OUTCOME_SUCCESS,
                detail=detail,
            )
            return

        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=audit_action,
            resource_type=resource_type.value,
            resource_id=resource_id,
            outcome=OUTCOME_DENIED,
            detail=f"{detail} — denied: {decision.reason}",
        )
        raise AuthorizationError(
            decision.reason,
            resource_type=resource_type.value,
            resource_id=resource_id,
            action=action.value,
        )

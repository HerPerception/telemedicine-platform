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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, FrozenSet, List, Optional, Tuple

from telemedicine.audit import OUTCOME_DENIED, OUTCOME_SUCCESS, AuditLog
from telemedicine.authorization import AccessScope, Action, Authorizer, ResourceType
from telemedicine.errors import AuthorizationError, ValidationError
from telemedicine.medications import validate_dispensing_identity
from telemedicine.models import Role, UserAccount
from telemedicine.repositories import ClinicalRepository, InMemoryClinicalRepository

MEDICATION_CATALOG_SYSTEM = "https://telemedicine.example.org/CodeSystem/medication"

# Audit actions.
ACTION_RECORD_READ = "record.read"
# Added by ENG-006 (the FHIR API).
ACTION_RECORD_UPDATE = "record.update"
ACTION_RECORD_CREATE = "record.create"
ACTION_PRESCRIPTION_CREATE = "prescription.create"
ACTION_PRESCRIPTION_READ = "prescription.read"
# Added by ENG-005 (e-prescriptions).
ACTION_STATUS_CHANGE = "prescription.status_change"


@dataclass(frozen=True)
class PatientRecord:
    patient_id: str
    user_id: str
    display_name: str
    date_of_birth: Optional[str] = None
    # Added by ENG-006 (the FHIR API): the demographics that ENG-001's
    # `patient` table defines and that the FHIR Patient mapping projects.
    mrn: Optional[str] = None
    family_name: Optional[str] = None
    given_names: Tuple[str, ...] = ()
    gender: str = "unknown"
    phone: Optional[str] = None
    email: Optional[str] = None
    address_line: Tuple[str, ...] = ()
    address_city: Optional[str] = None
    address_region: Optional[str] = None
    address_postal_code: Optional[str] = None
    address_country: Optional[str] = None


@dataclass(frozen=True)
class PractitionerRecord:
    """A clinician's record.

    Added by ENG-005 (e-prescriptions): the prescription document states who
    prescribed the medication, and the prescription is tied to the
    practitioner row of the clinical model.
    """

    practitioner_id: str
    user_id: str
    display_name: str
    identifier: Optional[str] = None
    specialty: Optional[str] = None
    # Added by ENG-006 (the FHIR API).
    family_name: Optional[str] = None
    given_names: Tuple[str, ...] = ()
    credentials: Tuple[str, ...] = ()
    gender: str = "unknown"
    license_number: Optional[str] = None
    license_region: Optional[str] = None


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
    # The slot this appointment occupies. Added by ENG-003 (booking): the
    # `appointment.slot_id` column of ENG-001's schema requires it, and the
    # booking service needs it to free a slot on reschedule or cancellation.
    slot_id: Optional[str] = None
    # Added by ENG-006 (the FHIR API): the columns of ENG-001's
    # `appointment` table that the FHIR mapping projects.
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    patient_note: Optional[str] = None
    created_at: Optional[datetime] = None
    # Added by ENG-009: the schema has always required a cancellation to
    # carry a reason and a moment, and the database refuses a cancelled
    # appointment without them. The domain had nowhere to put them.
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None


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
    # Added by ENG-006 (the FHIR API): the columns of ENG-001's `encounter`
    # table that the FHIR mapping projects.
    chief_complaint: Optional[str] = None
    clinical_note: Optional[str] = None


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
    # Added by ENG-006 (the FHIR API): the columns of ENG-001's
    # `medication_request` table that the FHIR mapping projects.
    notes: Optional[str] = None
    refills: Optional[int] = None
    dispense_quantity: Optional[float] = None
    route_text: Optional[str] = None
    dose_quantity: Optional[float] = None
    dose_unit: Optional[str] = None
    duration_days: Optional[int] = None
    # Added by ENG-016: the Nigerian dispensing identity. A pharmacy
    # dispenses by the brand and the NAFDAC registration number; the code
    # above is what the safety checks work on. Both are needed.
    brand_name: str = ""
    generic_name: str = ""
    strength: Optional[str] = None
    nafdac_number: str = ""


class RecordsService:
    """Reads clinical records and issues prescriptions, with audit and scoping."""

    def __init__(self, authorizer: Optional[Authorizer] = None,
                 audit: Optional[AuditLog] = None,
                 repository: Optional[ClinicalRepository] = None):
        self.authorizer = authorizer if authorizer is not None else Authorizer()
        self.audit = audit if audit is not None else AuditLog()
        # Where the records live. The default is the memory of one process;
        # a deployment passes the database one.
        self.repository: ClinicalRepository = (
            repository if repository is not None else InMemoryClinicalRepository())

    # -- registration of clinical data ------------------------------------
    # These mirror the write paths of the application. They exist so that the
    # access-control rules can be exercised; they are not authorization
    # boundaries themselves and must not be exposed over the API.

    def add_patient(self, patient: PatientRecord) -> PatientRecord:
        return self.repository.save_patient(patient)

    def add_practitioner(self, practitioner: PractitionerRecord) -> PractitionerRecord:
        return self.repository.save_practitioner(practitioner)

    def patients_treated_by(self, practitioner_user_id: str) -> List[PatientRecord]:
        """The patients a clinician treats, by their appointment or encounter."""
        return [patient for patient in self.repository.list_patients()
                if practitioner_user_id in self._treating_user_ids_for_patient(patient.patient_id)]

    def practitioners_treating(self, patient_user_id: str) -> List[PractitionerRecord]:
        """The clinicians who treat a patient, by their appointment or encounter."""
        user_ids = set()
        for appointment in self.repository.list_appointments():
            if appointment.patient_user_id == patient_user_id:
                user_ids.add(appointment.practitioner_user_id)
        for encounter in self.repository.list_encounters():
            if encounter.patient_user_id == patient_user_id:
                user_ids.add(encounter.practitioner_user_id)
        return [practitioner for practitioner in self.repository.list_practitioners()
                if practitioner.user_id in user_ids]

    def list_patients(self) -> List[PatientRecord]:
        """Every patient record. The caller filters it by scope."""
        return self.repository.list_patients()

    def list_practitioners(self) -> List[PractitionerRecord]:
        """Every practitioner record. The caller filters it by scope."""
        return self.repository.list_practitioners()

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Return an appointment without auditing the access.

        For internal use, for example to find the window of a consultation
        room. Reading an appointment *for a user* goes through
        :meth:`read_appointment`, which authorizes and audits.
        """
        return self.repository.get_appointment(appointment_id)

    def list_appointments(self) -> List[Appointment]:
        return self.repository.list_appointments()

    def list_encounters(self) -> List[Encounter]:
        return self.repository.list_encounters()

    def get_encounter(self, encounter_id: str) -> Optional[Encounter]:
        """Return an encounter without auditing the access.

        For internal use. Reading an encounter *for a user* goes through
        :meth:`read_encounter`, which authorizes and audits.
        """
        return self.repository.get_encounter(encounter_id)

    def list_prescriptions(self) -> List[Prescription]:
        return self.repository.list_prescriptions()

    def appointment_for_slot(self, slot_id: str) -> Optional[Appointment]:
        """The appointment that occupies a slot, if any."""
        return self.repository.appointment_for_slot(slot_id)

    def patient_record(self, patient_id: str) -> Optional[PatientRecord]:
        return self.repository.get_patient(patient_id)

    def patient_access_scope(self, patient_id: str) -> AccessScope:
        """The access scope of a patient's record.

        This is for checks that are *not* reads of the record itself — the
        consent state of a patient, for instance, which a clinician who
        treats them may see without the clinical record being read.

        The scope carries the patient's own account id in ``owner_user_id``,
        which is where a consent record is keyed: a consent belongs to the
        account, not to the clinical row.
        """
        patient = self._require_patient(patient_id)
        return self._patient_scope(patient)

    def practitioner_record(self, practitioner_id: str) -> Optional[PractitionerRecord]:
        return self.repository.get_practitioner(practitioner_id)

    def add_appointment(self, appointment: Appointment) -> Appointment:
        return self.repository.save_appointment(appointment)

    def add_encounter(self, encounter: Encounter) -> Encounter:
        return self.repository.save_encounter(encounter)

    # -- lookups used to build the access scope ---------------------------

    def _treating_user_ids_for_patient(self, patient_id: str) -> FrozenSet[str]:
        """The clinicians who have an appointment or an encounter with a patient.

        This is the treatment relationship the authorization rules rely on. It
        is derived from the data, never from a flag that someone can forget
        to set.
        """
        treating = set()
        for appointment in self.repository.list_appointments():
            if appointment.patient_id == patient_id:
                treating.add(appointment.practitioner_user_id)
        for encounter in self.repository.list_encounters():
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

    # -- writes for the FHIR API (added by ENG-006) ----------------------
    # The API needs a write path for the resources it exposes. Each of these
    # authorizes the change and audits it, exactly like the read paths.

    def read_practitioner_record(self, actor: UserAccount,
                                 practitioner_id: str) -> PractitionerRecord:
        """Read a practitioner record. Only the practitioner themselves."""
        practitioner = self._require_practitioner(practitioner_id)
        scope = AccessScope(owner_user_id=practitioner.user_id)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.PRACTITIONER, scope, practitioner_id,
            audit_action=ACTION_RECORD_READ, detail=f"read practitioner record {practitioner_id}",
        )
        return practitioner

    def update_patient(self, actor: UserAccount, patient_id: str,
                       **changes) -> PatientRecord:
        """Change a patient's own demographics."""
        patient = self._require_patient(patient_id)
        scope = AccessScope(owner_user_id=patient.user_id)
        self._authorize_and_audit(
            actor, Action.UPDATE, ResourceType.PATIENT, scope, patient_id,
            audit_action=ACTION_RECORD_UPDATE, detail=f"update patient record {patient_id}",
        )
        updated = replace(patient, **changes)
        return self.repository.save_patient(updated)

    def update_practitioner(self, actor: UserAccount, practitioner_id: str,
                            **changes) -> PractitionerRecord:
        """Change a practitioner's own details."""
        practitioner = self._require_practitioner(practitioner_id)
        scope = AccessScope(owner_user_id=practitioner.user_id)
        self._authorize_and_audit(
            actor, Action.UPDATE, ResourceType.PRACTITIONER, scope, practitioner_id,
            audit_action=ACTION_RECORD_UPDATE,
            detail=f"update practitioner record {practitioner_id}",
        )
        updated = replace(practitioner, **changes)
        return self.repository.save_practitioner(updated)

    def create_encounter(self, actor: UserAccount, appointment_id: str, *,
                         started_at: Optional[datetime] = None,
                         ended_at: Optional[datetime] = None,
                         status: str = "in-progress",
                         chief_complaint: Optional[str] = None,
                         clinical_note: Optional[str] = None) -> Encounter:
        """Record the encounter of a booked appointment.

        Only the clinician who delivers the appointment may record it, and
        the encounter inherits the appointment's patient and practitioner.
        """
        appointment = self.repository.get_appointment(appointment_id)
        if appointment is None:
            raise ValidationError(f"no appointment with id '{appointment_id}'")
        if any(encounter.appointment_id == appointment_id
               for encounter in self.repository.list_encounters()):
            raise ValidationError("an encounter already exists for this appointment")
        scope = self._appointment_scope(appointment)
        self._authorize_and_audit(
            actor, Action.CREATE, ResourceType.ENCOUNTER, scope, appointment_id,
            audit_action=ACTION_RECORD_CREATE, detail=f"record encounter for {appointment_id}",
        )
        encounter = Encounter(
            encounter_id=str(uuid.uuid4()),
            appointment_id=appointment.appointment_id,
            patient_id=appointment.patient_id,
            practitioner_id=appointment.practitioner_id,
            patient_user_id=appointment.patient_user_id,
            practitioner_user_id=appointment.practitioner_user_id,
            status=status,
            started_at=started_at or appointment.starts_at,
            ended_at=ended_at,
            chief_complaint=chief_complaint,
            clinical_note=clinical_note,
        )
        return self.repository.save_encounter(encounter)

    def update_encounter(self, actor: UserAccount, encounter_id: str,
                         **changes) -> Encounter:
        """Change an encounter: its status, its note or its end time."""
        encounter = self.repository.get_encounter(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        scope = self._encounter_scope(encounter)
        self._authorize_and_audit(
            actor, Action.UPDATE, ResourceType.ENCOUNTER, scope, encounter_id,
            audit_action=ACTION_RECORD_UPDATE, detail=f"update encounter {encounter_id}",
        )
        updated = replace(encounter, **changes)
        return self.repository.save_encounter(updated)

    def _require_practitioner(self, practitioner_id: str) -> PractitionerRecord:
        practitioner = self.repository.get_practitioner(practitioner_id)
        if practitioner is None:
            raise ValidationError(f"no practitioner with id '{practitioner_id}'")
        return practitioner

    def read_appointment(self, actor: UserAccount, appointment_id: str) -> Appointment:
        appointment = self.repository.get_appointment(appointment_id)
        if appointment is None:
            raise ValidationError(f"no appointment with id '{appointment_id}'")
        scope = self._appointment_scope(appointment)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.APPOINTMENT, scope, appointment_id,
            audit_action=ACTION_RECORD_READ, detail=f"read appointment {appointment_id}",
        )
        return appointment

    def read_encounter(self, actor: UserAccount, encounter_id: str) -> Encounter:
        encounter = self.repository.get_encounter(encounter_id)
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
                           brand_name: str, generic_name: str, nafdac_number: str,
                           strength: Optional[str] = None,
                           authored_on: Optional[datetime] = None,
                           **details) -> Prescription:
        """Issue a prescription against an encounter.

        Only the clinician who treated the encounter may issue it, and the
        prescription inherits the encounter's patient and prescriber — the
        same pairing the database enforces with a composite foreign key.

        The audit entry of a successful issue identifies the prescription
        that was created. A refused attempt identifies the encounter it was
        refused for, because no prescription exists to point at; both
        entries name the encounter in their detail.

        **The Nigerian dispensing identity is required** (ENG-016): the
        brand name, the generic name and the NAFDAC registration number. A
        prescription without them cannot be dispensed, so it is refused here
        rather than issued and found out at the pharmacy counter.
        """
        encounter = self.repository.get_encounter(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        scope = self._encounter_scope(encounter)
        decision = self.authorizer.decide(actor, Action.CREATE,
                                           ResourceType.MEDICATION_REQUEST, scope)
        if not decision.allowed:
            self.audit.append(
                actor_user_id=actor.user_id,
                actor_role=actor.role.value,
                action=ACTION_PRESCRIPTION_CREATE,
                resource_type=ResourceType.MEDICATION_REQUEST.value,
                resource_id=encounter_id,
                outcome=OUTCOME_DENIED,
                detail=f"issue a prescription for encounter {encounter_id} — denied: "
                       f"{decision.reason}",
            )
            raise AuthorizationError(
                decision.reason,
                resource_type=ResourceType.MEDICATION_REQUEST.value,
                resource_id=encounter_id,
                action=Action.CREATE.value,
            )

        # The content is checked after the authorization, so that a refused
        # attempt is audited as a refusal whatever the body said.
        if not medication_code or not medication_display or not dosage_text:
            raise ValidationError(
                "a prescription needs a medication code, a display name and dosage text")
        if not generic_name or not str(generic_name).strip():
            raise ValidationError(
                "a prescription needs the generic name of the medicine, so that the "
                "patient and the pharmacist know what is being dispensed")
        # The brand and the registration number are checked together, and the
        # number is checked for its shape: a number that could not be right
        # is worse than no number, because it looks right.
        nafdac_number = validate_dispensing_identity(brand_name, nafdac_number)

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
            brand_name=str(brand_name).strip(),
            generic_name=str(generic_name).strip(),
            strength=str(strength).strip() if strength else None,
            nafdac_number=nafdac_number,
            authored_on=authored_on or datetime.now(timezone.utc),
            **details,
        )
        self.repository.save_prescription(prescription)
        self.audit.append(
            actor_user_id=actor.user_id,
            actor_role=actor.role.value,
            action=ACTION_PRESCRIPTION_CREATE,
            resource_type=ResourceType.MEDICATION_REQUEST.value,
            resource_id=prescription.prescription_id,
            outcome=OUTCOME_SUCCESS,
            detail=f"issued a prescription for encounter {encounter_id}",
        )
        return prescription

    def read_prescription(self, actor: UserAccount, prescription_id: str) -> Prescription:
        """Read a prescription. The patient it is for, or the clinician who issued it."""
        prescription = self.repository.get_prescription(prescription_id)
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
        encounter = self.repository.get_encounter(encounter_id)
        if encounter is None:
            raise ValidationError(f"no encounter with id '{encounter_id}'")
        scope = self._encounter_scope(encounter)
        self._authorize_and_audit(
            actor, Action.READ, ResourceType.MEDICATION_REQUEST, scope, encounter_id,
            audit_action=ACTION_PRESCRIPTION_READ,
            detail=f"list prescriptions for encounter {encounter_id}",
        )
        return self.repository.prescriptions_for_encounter(encounter_id)

    def get_prescription(self, prescription_id: str) -> Prescription:
        """Return a prescription without auditing the access.

        For internal use, for example to check the current status before a
        transition. Reading a prescription *for a user* goes through
        :meth:`read_prescription`, which authorizes and audits.
        """
        prescription = self.repository.get_prescription(prescription_id)
        if prescription is None:
            raise ValidationError(f"no prescription with id '{prescription_id}'")
        return prescription

    def update_prescription(self, actor: UserAccount, prescription_id: str,
                            **changes) -> Prescription:
        """Change the details of a prescription. Authorized and audited."""
        prescription = self.get_prescription(prescription_id)
        scope = self._prescription_scope(prescription)
        self._authorize_and_audit(
            actor, Action.UPDATE, ResourceType.MEDICATION_REQUEST, scope, prescription_id,
            audit_action=ACTION_STATUS_CHANGE,
            detail=f"update prescription {prescription_id}",
        )
        updated = replace(prescription, **changes)
        return self.repository.save_prescription(updated)

    def update_prescription_status(self, actor: UserAccount, prescription_id: str,
                                   status: str, *, reason: str = "") -> Prescription:
        """Change the status of a prescription. Authorized and audited.

        Added by ENG-005 (e-prescriptions): the prescription lifecycle needs
        a write path that only the treating clinician may use.
        """
        prescription = self.get_prescription(prescription_id)
        scope = self._prescription_scope(prescription)
        self._authorize_and_audit(
            actor, Action.UPDATE, ResourceType.MEDICATION_REQUEST, scope, prescription_id,
            audit_action=ACTION_STATUS_CHANGE,
            detail=f"change status to {status}"
                   + (f": {reason}" if reason else ""),
        )
        updated = replace(prescription, status=status)
        return self.repository.save_prescription(updated)

    # -- internals --------------------------------------------------------

    def _require_patient(self, patient_id: str) -> PatientRecord:
        patient = self.repository.get_patient(patient_id)
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

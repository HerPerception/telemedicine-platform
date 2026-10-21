"""The read and write paths of the FHIR API.

This is the layer between the HTTP surface and the domain services. It does
three things:

* it turns a FHIR resource into the arguments the domain services expect,
  and the other way round;
* it calls the domain services, which authorize the call and write the audit
  entry — no read or write reaches the data without passing through them;
* it keeps the domain's rules intact. A patient may not read another
  patient's record, a prescription may only be issued by the clinician who
  treated the encounter, and a clinical record is never deleted.

Every method raises :class:`~telemedicine.errors.ValidationError` for input
it cannot make sense of, :class:`~telemedicine.errors.AuthorizationError` when
the caller may not do it, and :class:`~telemedicine.errors.AuthenticationError`
when the caller is not who they say they are. The server turns those into the
right HTTP status.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from telemedicine.booking import BookingService
from telemedicine.errors import ValidationError
from telemedicine.fhir.serialization import (
    MEDICATION_BRAND_NAME_EXTENSION,
    MEDICATION_GENERIC_NAME_EXTENSION,
    MEDICATION_STRENGTH_EXTENSION,
)
from telemedicine.medications import NAFDAC_SYSTEM
from telemedicine.models import Role, UserAccount
from telemedicine.prescriptions import PrescriptionService
from telemedicine.records import RecordsService


def reference_id(reference: str) -> Tuple[str, str]:
    """Split ``Type/id`` into its parts."""
    if not isinstance(reference, str) or "/" not in reference:
        raise ValidationError(f"'{reference}' is not a valid reference")
    resource_type, _, identifier = reference.rpartition("/")
    if not resource_type or not identifier:
        raise ValidationError(f"'{reference}' is not a valid reference")
    return resource_type, identifier


class FhirRepository:
    """The API's view of the clinical data."""

    def __init__(self, records: RecordsService, booking: BookingService,
                 prescriptions: PrescriptionService):
        self.records = records
        self.booking = booking
        self.prescriptions = prescriptions

    # -- the ids the API knows about --------------------------------------

    def known_ids(self) -> Dict[str, set]:
        """The ids that exist, so that a reference can be checked."""
        return {
            "Patient": {patient.patient_id for patient in self.records.list_patients()},
            "Practitioner": {practitioner.practitioner_id
                             for practitioner in self.records.list_practitioners()},
            "Appointment": {appointment.appointment_id
                            for appointment in self.records.list_appointments()},
            "Encounter": {encounter.encounter_id
                          for encounter in self.records.list_encounters()},
            "MedicationRequest": {prescription.prescription_id
                                  for prescription in self.records.list_prescriptions()},
        }

    # -- patients ----------------------------------------------------------

    def read_patient(self, actor: UserAccount, patient_id: str):
        return self.records.read_patient_record(actor, patient_id)

    def search_patients(self, actor: UserAccount) -> List:
        if actor.role == Role.PATIENT:
            own = [patient for patient in self.records.list_patients()
                   if patient.user_id == actor.user_id]
            return own
        return self.records.patients_treated_by(actor.user_id)

    def update_patient(self, actor: UserAccount, patient_id: str, resource: dict):
        changes = _patient_changes(resource)
        if not changes:
            raise ValidationError("the resource carries no updatable fields")
        return self.records.update_patient(actor, patient_id, **changes)

    # -- practitioners -----------------------------------------------------

    def read_practitioner(self, actor: UserAccount, practitioner_id: str):
        return self.records.read_practitioner_record(actor, practitioner_id)

    def search_practitioners(self, actor: UserAccount) -> List:
        if actor.role == Role.PRACTITIONER:
            return [practitioner for practitioner in self.records.list_practitioners()
                    if practitioner.user_id == actor.user_id]
        return self.records.practitioners_treating(actor.user_id)

    def update_practitioner(self, actor: UserAccount, practitioner_id: str, resource: dict):
        changes = _practitioner_changes(resource)
        if not changes:
            raise ValidationError("the resource carries no updatable fields")
        return self.records.update_practitioner(actor, practitioner_id, **changes)

    # -- appointments ------------------------------------------------------

    def read_appointment(self, actor: UserAccount, appointment_id: str):
        return self.records.read_appointment(actor, appointment_id)

    def search_appointments(self, actor: UserAccount) -> List:
        return [appointment for appointment in self.records.list_appointments()
                if actor.user_id in (appointment.patient_user_id,
                                     appointment.practitioner_user_id)]

    def create_appointment(self, actor: UserAccount, resource: dict):
        """Book a slot.

        The FHIR resource names the slot in ``Appointment.slot`` and the
        patient in ``Appointment.participant``.
        """
        slot_id = _slot_id(resource)
        patient_id = _patient_id(resource)
        patient_user_id = None
        if actor.role != Role.PATIENT:
            if patient_id is None:
                raise ValidationError("the appointment must name the patient")
            patient = self.records.patient_record(patient_id)
            if patient is None:
                raise ValidationError(f"no patient with id '{patient_id}'")
            patient_user_id = patient.user_id
        return self.booking.book(actor, slot_id, patient_user_id=patient_user_id)

    def update_appointment(self, actor: UserAccount, appointment_id: str, resource: dict):
        """Move or cancel an appointment."""
        current = self.records.read_appointment(actor, appointment_id)
        status = resource.get("status")
        new_slot_id = _slot_id(resource)
        if new_slot_id and new_slot_id != current.slot_id:
            return self.booking.reschedule(actor, appointment_id, new_slot_id)
        if status and status != current.status:
            if status == "cancelled":
                reason = _cancellation_reason(resource)
                return self.booking.cancel(actor, appointment_id, reason=reason)
            raise ValidationError(
                f"an appointment can only be changed to 'cancelled' here, not '{status}'")
        raise ValidationError("the resource carries no change to apply")

    # -- encounters --------------------------------------------------------

    def read_encounter(self, actor: UserAccount, encounter_id: str):
        return self.records.read_encounter(actor, encounter_id)

    def search_encounters(self, actor: UserAccount) -> List:
        return [encounter for encounter in self.records.list_encounters()
                if actor.user_id in (encounter.patient_user_id,
                                     encounter.practitioner_user_id)]

    def create_encounter(self, actor: UserAccount, resource: dict):
        appointment_id = _encounter_appointment_id(resource)
        if not appointment_id:
            raise ValidationError("the encounter must reference the appointment it belongs to")
        details = _encounter_details(resource)
        return self.records.create_encounter(actor, appointment_id, **details)

    def update_encounter(self, actor: UserAccount, encounter_id: str, resource: dict):
        changes = _encounter_details(resource, updating=True)
        if not changes:
            raise ValidationError("the resource carries no updatable fields")
        return self.records.update_encounter(actor, encounter_id, **changes)

    # -- medication requests -----------------------------------------------

    def read_medication_request(self, actor: UserAccount, request_id: str):
        return self.records.read_prescription(actor, request_id)

    def search_medication_requests(self, actor: UserAccount) -> List:
        return [prescription for prescription in self.records.list_prescriptions()
                if actor.user_id in (prescription.patient_user_id,
                                     prescription.prescriber_user_id)]

    def create_medication_request(self, actor: UserAccount, resource: dict):
        encounter_id = _encounter_id(resource)
        if not encounter_id:
            raise ValidationError("the prescription must reference the encounter it was issued in")
        medication = _medication(resource)
        dosage_text = _dosage_text(resource)
        details = _prescription_details(resource)
        # The Nigerian dispensing identity (ENG-016): the brand and the
        # generic name come from the extensions, the registration number from
        # the NAFDAC coding. None of them is optional.
        brand_name = details.pop("brand_name", None) or ""
        generic_name = details.pop("generic_name", None) or ""
        strength = details.pop("strength", None)
        prescription, _document = self.prescriptions.issue(
            actor, encounter_id,
            medication_code=medication[1],
            medication_display=medication[2],
            dosage_text=dosage_text,
            brand_name=brand_name,
            generic_name=generic_name,
            nafdac_number=medication[3] or "",
            strength=strength,
            **details,
        )
        return prescription

    def update_medication_request(self, actor: UserAccount, request_id: str, resource: dict):
        status = resource.get("status")
        details = _prescription_details(resource)
        updated = None
        if status:
            reason = ""
            if status == "cancelled":
                # A cancellation needs a reason; the API takes it from
                # MedicationRequest.statusReason, or from a note.
                reason = (resource.get("statusReason") or {}).get("text") or ""
                if not reason:
                    for note in resource.get("note", []) or []:
                        if note.get("text"):
                            reason = note["text"]
                            break
            updated = self.prescriptions.change_status(actor, request_id, status, reason=reason)
        if details:
            updated = self.records.update_prescription(actor, request_id, **details)
        if updated is None:
            raise ValidationError("the resource carries no change to apply")
        return updated


# --------------------------------------------------------------------------
# Reading a FHIR resource into domain arguments
# --------------------------------------------------------------------------


def _patient_id(resource: dict) -> Optional[str]:
    for participant in resource.get("participant", []) or []:
        actor = participant.get("actor") or {}
        reference = actor.get("reference")
        if reference and reference.startswith("Patient/"):
            return reference.split("/", 1)[1]
    return None


def _slot_id(resource: dict) -> Optional[str]:
    for slot in resource.get("slot", []) or []:
        reference = slot.get("reference")
        if reference and reference.startswith("Slot/"):
            return reference.split("/", 1)[1]
    return None


def _encounter_id(resource: dict) -> Optional[str]:
    reference = (resource.get("encounter") or {}).get("reference")
    if reference and reference.startswith("Encounter/"):
        return reference.split("/", 1)[1]
    return None


def _encounter_appointment_id(resource: dict) -> Optional[str]:
    for appointment in resource.get("appointment", []) or []:
        reference = appointment.get("reference")
        if reference and reference.startswith("Appointment/"):
            return reference.split("/", 1)[1]
    return None


def _medication(resource: dict) -> Tuple[str, str, str, Optional[str]]:
    """The medication of a prescription: the coded concept and the NAFDAC number.

    The first coding is the coded concept the safety checks work on; the
    NAFDAC registration number is found wherever it is, because a client may
    put it first (ENG-016).
    """
    concept = resource.get("medicationCodeableConcept") or {}
    codings = concept.get("coding") or []
    if not codings:
        raise ValidationError("the prescription must name a medication")
    coding = codings[0]
    code = coding.get("code")
    if not code:
        raise ValidationError("the medication must have a code")
    display = coding.get("display") or concept.get("text") or code
    return coding.get("system"), code, display, _nafdac_code(codings)


def _nafdac_code(codings: List[dict]) -> Optional[str]:
    """The NAFDAC registration number, if the resource carries one."""
    for coding in codings:
        if not isinstance(coding, dict):
            continue
        if coding.get("system") == NAFDAC_SYSTEM and coding.get("code"):
            return str(coding["code"])
    return None


def _dosage_text(resource: dict) -> str:
    dosages = resource.get("dosageInstruction") or []
    if not dosages or not dosages[0].get("text"):
        raise ValidationError("the prescription must have dosage instructions")
    return dosages[0]["text"]


def _cancellation_reason(resource: dict) -> str:
    reason = resource.get("cancelationReason") or {}
    return reason.get("text") or "cancelled by the API"


def _patient_changes(resource: dict) -> dict:
    changes: dict = {}
    for name in resource.get("name", []) or []:
        if name.get("family"):
            changes["family_name"] = name["family"]
        if name.get("given"):
            changes["given_names"] = tuple(name["given"])
        break
    for telecom in resource.get("telecom", []) or []:
        if telecom.get("system") == "phone":
            changes["phone"] = telecom.get("value")
        elif telecom.get("system") == "email":
            changes["email"] = telecom.get("value")
    if resource.get("gender"):
        changes["gender"] = resource["gender"]
    if resource.get("birthDate"):
        changes["date_of_birth"] = resource["birthDate"]
    for address in resource.get("address", []) or []:
        if address.get("line"):
            changes["address_line"] = tuple(address["line"])
        if address.get("city"):
            changes["address_city"] = address["city"]
        if address.get("state"):
            changes["address_region"] = address["state"]
        if address.get("postalCode"):
            changes["address_postal_code"] = address["postalCode"]
        if address.get("country"):
            changes["address_country"] = address["country"]
        break
    return changes


def _practitioner_changes(resource: dict) -> dict:
    changes: dict = {}
    for name in resource.get("name", []) or []:
        if name.get("family"):
            changes["family_name"] = name["family"]
        if name.get("given"):
            changes["given_names"] = tuple(name["given"])
        if name.get("suffix"):
            changes["credentials"] = tuple(name["suffix"])
        break
    for qualification in resource.get("qualification", []) or []:
        identifiers = qualification.get("identifier") or []
        if identifiers and identifiers[0].get("value"):
            changes["license_number"] = identifiers[0]["value"]
        code = qualification.get("code") or {}
        if code.get("text"):
            changes["specialty"] = code["text"]
        issuer = qualification.get("issuer") or {}
        if issuer.get("display"):
            changes["license_region"] = issuer["display"]
        break
    if resource.get("gender"):
        changes["gender"] = resource["gender"]
    return changes


def _encounter_details(resource: dict, updating: bool = False) -> dict:
    details: dict = {}
    if resource.get("status"):
        details["status"] = resource["status"]
    period = resource.get("period") or {}
    if period.get("start") and not updating:
        details["started_at"] = period["start"]
    if period.get("end"):
        details["ended_at"] = period["end"]
    if not updating:
        for reason in resource.get("reasonCode", []) or []:
            if reason.get("text"):
                details["chief_complaint"] = reason["text"]
            break
    for extension in resource.get("extension", []) or []:
        if extension.get("url", "").endswith("/encounter-clinical-note"):
            if extension.get("valueString"):
                details["clinical_note"] = extension["valueString"]
    return details


def _medication_extensions(resource: dict) -> dict:
    """The dispensing identity, carried by the extensions (ENG-016)."""
    values: dict = {}
    for extension in resource.get("extension") or []:
        if not isinstance(extension, dict):
            continue
        url = extension.get("url", "")
        value = extension.get("valueString")
        if not value:
            continue
        if url == MEDICATION_BRAND_NAME_EXTENSION:
            values["brand_name"] = value
        elif url == MEDICATION_GENERIC_NAME_EXTENSION:
            values["generic_name"] = value
        elif url == MEDICATION_STRENGTH_EXTENSION:
            values["strength"] = value
    return values


def _prescription_details(resource: dict) -> dict:
    details: dict = {}
    details.update(_medication_extensions(resource))
    notes = resource.get("note") or []
    if notes and notes[0].get("text"):
        details["notes"] = notes[0]["text"]
    dispense = resource.get("dispenseRequest") or {}
    if dispense.get("numberOfRepeatsAllowed") is not None:
        details["refills"] = dispense["numberOfRepeatsAllowed"]
    quantity = dispense.get("quantity") or {}
    if quantity.get("value") is not None:
        details["dispense_quantity"] = quantity["value"]
    dosages = resource.get("dosageInstruction") or []
    if dosages:
        dosage = dosages[0]
        route = dosage.get("route") or {}
        if route.get("text"):
            details["route_text"] = route["text"]
        for rate in dosage.get("doseAndRate", []) or []:
            dose = rate.get("doseQuantity") or {}
            if dose.get("value") is not None:
                details["dose_quantity"] = dose["value"]
            if dose.get("unit"):
                details["dose_unit"] = dose["unit"]
            break
        timing = dosage.get("timing") or {}
        repeat = timing.get("repeat") or {}
        bounds = repeat.get("boundsDuration") or {}
        if bounds.get("value") is not None:
            details["duration_days"] = bounds["value"]
    return details

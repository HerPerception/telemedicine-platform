"""From the domain model to FHIR R4 resources.

Every function here implements one row of the mapping table in
``docs/fhir-mappings.md``: the element names, the cardinalities, the
identifier systems and the code systems are exactly those the mapping
declares, so a resource produced here satisfies the profile that the API
publishes.

The resources are plain dictionaries, so they can be validated with
:func:`telemedicine.fhir.validation.validate_resource` and then serialised
as JSON without anything in between.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from telemedicine.records import (
    Appointment,
    Encounter,
    PatientRecord,
    PractitionerRecord,
    Prescription,
)

# Identifier systems (docs/fhir-mappings.md §2.1)
MRN_SYSTEM = "https://telemedicine.example.org/identifier/mrn"
NPI_SYSTEM = "http://hl7.org/fhir/sid/us-npi"
LICENSE_SYSTEM = "https://telemedicine.example.org/identifier/license"
APPOINTMENT_SYSTEM = "https://telemedicine.example.org/identifier/appointment"
ENCOUNTER_SYSTEM = "https://telemedicine.example.org/identifier/encounter"
PRESCRIPTION_SYSTEM = "https://telemedicine.example.org/identifier/prescription"

# The profiles the API publishes (docs/fhir-mappings.md §2.3)
PROFILE_BASE = "https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-"

# Code systems
PARTICIPATION_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ParticipationType"
IDENTIFIER_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v2-0203"
ENCOUNTER_CLASS_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode"
ENCOUNTER_TYPE_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
UCUM_SYSTEM = "http://unitsofmeasure.org"

# The one extension this project declares (docs/fhir-mappings.md §2.4)
CLINICAL_NOTE_EXTENSION = (
    "https://telemedicine.example.org/fhir/StructureDefinition/encounter-clinical-note")

FHIR_VERSION = "4.0.1"
FHIR_CONTENT_TYPE = "application/fhir+json; charset=utf-8"


def _instant(value: Optional[datetime]) -> Optional[str]:
    """Render an instant in the lexical form R4 expects: UTC with a Z."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _meta(profile_name: str) -> dict:
    return {"profile": [PROFILE_BASE + profile_name]}


def patient_resource(patient: PatientRecord) -> dict:
    """Project a patient record onto a FHIR ``Patient``."""
    resource: dict = {
        "resourceType": "Patient",
        "id": patient.patient_id,
        "meta": _meta("patient"),
    }
    if patient.mrn:
        resource["identifier"] = [{
            "use": "usual",
            "type": {"coding": [{
                "system": IDENTIFIER_TYPE_SYSTEM,
                "code": "MR",
                "display": "Medical Record Number",
            }]},
            "system": MRN_SYSTEM,
            "value": patient.mrn,
        }]

    family = patient.family_name or patient.display_name
    given = list(patient.given_names)
    if not given and family:
        given = [part for part in family.split(" ")[:-1]] or [family]
    name: dict = {"use": "official"}
    if family:
        name["family"] = family
    if given:
        name["given"] = given
    resource["name"] = [name]

    telecom = []
    if patient.phone:
        telecom.append({"system": "phone", "value": patient.phone, "use": "mobile"})
    if patient.email:
        telecom.append({"system": "email", "value": patient.email, "use": "home"})
    if telecom:
        resource["telecom"] = telecom

    resource["gender"] = patient.gender or "unknown"
    if patient.date_of_birth:
        resource["birthDate"] = patient.date_of_birth

    if any([patient.address_line, patient.address_city, patient.address_region,
            patient.address_postal_code, patient.address_country]):
        address: dict = {"use": "home"}
        if patient.address_line:
            address["line"] = list(patient.address_line)
        if patient.address_city:
            address["city"] = patient.address_city
        if patient.address_region:
            address["state"] = patient.address_region
        if patient.address_postal_code:
            address["postalCode"] = patient.address_postal_code
        if patient.address_country:
            address["country"] = patient.address_country
        resource["address"] = [address]
    return resource


def practitioner_resource(practitioner: PractitionerRecord) -> dict:
    """Project a practitioner record onto a FHIR ``Practitioner``."""
    resource: dict = {
        "resourceType": "Practitioner",
        "id": practitioner.practitioner_id,
        "meta": _meta("practitioner"),
    }
    if practitioner.identifier:
        resource["identifier"] = [{
            "use": "official",
            "system": NPI_SYSTEM,
            "value": practitioner.identifier,
        }]

    family = practitioner.family_name or practitioner.display_name
    given = list(practitioner.given_names)
    if not given and family:
        given = [part for part in family.split(" ")[:-1]] or [family]
    name: dict = {"use": "official"}
    if family:
        name["family"] = family
    if given:
        name["given"] = given
    if practitioner.credentials:
        name["suffix"] = list(practitioner.credentials)
    resource["name"] = [name]

    resource["gender"] = practitioner.gender or "unknown"

    if practitioner.license_number or practitioner.specialty:
        qualification: dict = {}
        if practitioner.license_number:
            qualification["identifier"] = [{
                "system": LICENSE_SYSTEM,
                "value": practitioner.license_number,
            }]
        if practitioner.specialty:
            qualification["code"] = {"text": practitioner.specialty}
        if practitioner.license_region:
            qualification["issuer"] = {"display": practitioner.license_region}
        resource["qualification"] = [qualification]
    return resource


def appointment_resource(appointment: Appointment) -> dict:
    """Project an appointment onto a FHIR ``Appointment``."""
    resource: dict = {
        "resourceType": "Appointment",
        "id": appointment.appointment_id,
        "meta": _meta("appointment"),
        "identifier": [{
            "use": "official",
            "system": APPOINTMENT_SYSTEM,
            "value": appointment.appointment_id,
        }],
        "status": appointment.status,
        "participant": [
            {
                "type": [{"coding": [{
                    "system": PARTICIPATION_TYPE_SYSTEM,
                    "code": "SBJ",
                    "display": "subject",
                }]}],
                "actor": {"reference": f"Patient/{appointment.patient_id}"},
                "required": "required",
                "status": "accepted",
            },
            {
                "type": [{"coding": [{
                    "system": PARTICIPATION_TYPE_SYSTEM,
                    "code": "PPR",
                    "display": "primary performer",
                }]}],
                "actor": {"reference": f"Practitioner/{appointment.practitioner_id}"},
                "required": "required",
                "status": "accepted",
            },
        ],
    }
    if appointment.reason_text:
        reason: dict = {"text": appointment.reason_text}
        if appointment.reason_code:
            reason["coding"] = [{
                "system": "http://snomed.info/sct",
                "code": appointment.reason_code,
            }]
        resource["reasonCode"] = [reason]
    start = _instant(appointment.starts_at)
    end = _instant(appointment.ends_at)
    if start:
        resource["start"] = start
    if end:
        resource["end"] = end
    if appointment.starts_at and appointment.ends_at:
        resource["minutesDuration"] = int(
            (appointment.ends_at - appointment.starts_at).total_seconds() // 60)
    if appointment.slot_id:
        resource["slot"] = [{"reference": f"Slot/{appointment.slot_id}"}]
    if appointment.created_at:
        resource["created"] = _instant(appointment.created_at)
    if appointment.patient_note:
        resource["comment"] = appointment.patient_note
    return resource


def encounter_resource(encounter: Encounter) -> dict:
    """Project an encounter onto a FHIR ``Encounter``."""
    resource: dict = {
        "resourceType": "Encounter",
        "id": encounter.encounter_id,
        "meta": _meta("encounter"),
        "identifier": [{
            "use": "official",
            "system": ENCOUNTER_SYSTEM,
            "value": encounter.encounter_id,
        }],
        "status": encounter.status,
        "class": {
            "system": ENCOUNTER_CLASS_SYSTEM,
            "code": "AMB",
            "display": "ambulatory",
        },
        "type": [{
            "coding": [{
                "system": ENCOUNTER_TYPE_SYSTEM,
                "code": "VR",
                "display": "virtual",
            }],
            "text": "Virtual consultation",
        }],
        "subject": {"reference": f"Patient/{encounter.patient_id}"},
        "participant": [{
            "type": [{"coding": [{
                "system": PARTICIPATION_TYPE_SYSTEM,
                "code": "PPR",
                "display": "primary performer",
            }]}],
            "individual": {"reference": f"Practitioner/{encounter.practitioner_id}"},
        }],
        "appointment": [{"reference": f"Appointment/{encounter.appointment_id}"}],
    }
    period: dict = {}
    start = _instant(encounter.started_at)
    end = _instant(encounter.ended_at)
    if start:
        period["start"] = start
    if end:
        period["end"] = end
    if period:
        resource["period"] = period
    if encounter.chief_complaint:
        resource["reasonCode"] = [{"text": encounter.chief_complaint}]
    if encounter.clinical_note:
        resource["extension"] = [{
            "url": CLINICAL_NOTE_EXTENSION,
            "valueString": encounter.clinical_note,
        }]
    return resource


def medication_request_resource(prescription: Prescription) -> dict:
    """Project a prescription onto a FHIR ``MedicationRequest``."""
    resource: dict = {
        "resourceType": "MedicationRequest",
        "id": prescription.prescription_id,
        "meta": _meta("medicationrequest"),
        "identifier": [{
            "use": "official",
            "system": PRESCRIPTION_SYSTEM,
            "value": prescription.prescription_id,
        }],
        "status": prescription.status,
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{
                "system": prescription.medication_system,
                "code": prescription.medication_code,
                "display": prescription.medication_display,
            }],
            "text": prescription.medication_display,
        },
        "subject": {"reference": f"Patient/{prescription.patient_id}"},
        "encounter": {"reference": f"Encounter/{prescription.encounter_id}"},
        "requester": {"reference": f"Practitioner/{prescription.prescriber_id}"},
    }
    if prescription.authored_on:
        resource["authoredOn"] = _instant(prescription.authored_on)
    if prescription.notes:
        resource["note"] = [{"text": prescription.notes}]

    dosage: dict = {"text": prescription.dosage_text}
    if prescription.route_text:
        dosage["route"] = {"text": prescription.route_text}
    if prescription.dose_quantity is not None:
        quantity = {"value": prescription.dose_quantity}
        if prescription.dose_unit:
            quantity["unit"] = prescription.dose_unit
            quantity["system"] = UCUM_SYSTEM
        dosage["doseAndRate"] = [{"doseQuantity": quantity}]
    if prescription.duration_days:
        dosage["timing"] = {"repeat": {"boundsDuration": {
            "value": prescription.duration_days,
            "unit": "days",
            "system": UCUM_SYSTEM,
            "code": "d",
        }}}
    resource["dosageInstruction"] = [dosage]

    if prescription.refills is not None or prescription.dispense_quantity is not None:
        dispense: dict = {}
        if prescription.refills is not None:
            dispense["numberOfRepeatsAllowed"] = prescription.refills
        if prescription.dispense_quantity is not None:
            quantity = {"value": prescription.dispense_quantity}
            if prescription.dose_unit:
                quantity["unit"] = prescription.dose_unit
                quantity["system"] = UCUM_SYSTEM
            dispense["quantity"] = quantity
        resource["dispenseRequest"] = dispense
    return resource


def operation_outcome(severity: str, code: str, diagnostics: str) -> dict:
    """An ``OperationOutcome``, which is how this API reports every error."""
    return {
        "resourceType": "OperationOutcome",
        "issue": [{
            "severity": severity,
            "code": code,
            "diagnostics": diagnostics,
        }],
    }


def capability_statement() -> dict:
    """The ``CapabilityStatement`` the API publishes at its metadata endpoint.

    It advertises what the server actually does. The search is a list of the
    resources the caller may see, not a query, so no search parameters are
    declared.
    """
    def resource(resource_type: str, interactions: List[str]) -> dict:
        return {
            "type": resource_type,
            "profile": PROFILE_BASE + resource_type.lower(),
            "interaction": [{"code": code} for code in interactions],
        }

    return {
        "resourceType": "CapabilityStatement",
        "status": "draft",
        "date": _instant(datetime.now(timezone.utc)),
        "kind": "instance",
        "fhirVersion": FHIR_VERSION,
        "format": ["json"],
        "rest": [{
            "mode": "server",
            "security": {
                "description": "A session token is required for every request.",
            },
            "resource": [
                resource("Patient", ["read", "update", "search"]),
                resource("Practitioner", ["read", "update", "search"]),
                resource("Appointment", ["read", "create", "update", "search"]),
                resource("Encounter", ["read", "create", "update", "search"]),
                resource("MedicationRequest", ["read", "create", "update", "search"]),
            ],
        }],
    }

#!/usr/bin/env python3
"""Validate the ENG-001 example FHIR R4 resources.

Usage:
    python3 scripts/validate_fhir_examples.py [EXAMPLES_DIR] [--json]

The script checks the example resources in ``docs/fhir/examples/`` against the
subset of FHIR R4 rules that the ENG-001 mapping declares:

* the resource type is one of the seven resources this project models;
* every top-level element is one the R4 StructureDefinition allows, and no
  element that R4 marks as required (min >= 1) is missing;
* the elements this project's profile requires are present;
* coded elements carry a code from the value set the mapping declares;
* identifiers, instants, dates and durations use the R4 lexical forms;
* references are well formed and resolve to another example when the target
  resource type is part of the example set;
* extensions use a URL this project has declared.

What it does NOT do: it is not a FHIR validator. It does not expand
terminology, evaluate FHIRPath invariants, or check profile conformance in
general. Full conformance validation belongs to ENG-006. The R4 element
tables below were taken from the published R4 StructureDefinitions on
2026-10-19; see docs/fhir-mappings.md for the source URLs.

Exit status is 0 when no errors are found and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# R4 element tables (from the published R4 StructureDefinitions, 2026-10-19)
# --------------------------------------------------------------------------

PROFILES = {
    "Patient": {
        "allowed": [
            "active", "address", "birthDate", "communication", "contact", "contained",
            "deceased[x]", "extension", "gender", "generalPractitioner", "id", "identifier",
            "implicitRules", "language", "link", "managingOrganization", "maritalStatus",
            "meta", "modifierExtension", "multipleBirth[x]", "name", "photo", "telecom", "text",
        ],
        "required": [],
    },
    "Practitioner": {
        "allowed": [
            "active", "address", "birthDate", "communication", "contained", "extension",
            "gender", "id", "identifier", "implicitRules", "language", "meta",
            "modifierExtension", "name", "photo", "qualification", "telecom", "text",
        ],
        "required": [],
    },
    "Schedule": {
        "allowed": [
            "active", "actor", "comment", "contained", "extension", "id", "identifier",
            "implicitRules", "language", "meta", "modifierExtension", "planningHorizon",
            "serviceCategory", "serviceType", "specialty", "text",
        ],
        "required": ["actor"],
    },
    "Slot": {
        "allowed": [
            "appointmentType", "comment", "contained", "end", "extension", "id", "identifier",
            "implicitRules", "language", "meta", "modifierExtension", "overbooked", "schedule",
            "serviceCategory", "serviceType", "specialty", "start", "status", "text",
        ],
        "required": ["end", "schedule", "start", "status"],
    },
    "Appointment": {
        "allowed": [
            "appointmentType", "basedOn", "cancelationReason", "comment", "contained",
            "created", "description", "end", "extension", "id", "identifier", "implicitRules",
            "language", "meta", "minutesDuration", "modifierExtension", "participant",
            "patientInstruction", "priority", "reasonCode", "reasonReference",
            "requestedPeriod", "serviceCategory", "serviceType", "slot", "specialty", "start",
            "status", "supportingInformation", "text",
        ],
        "required": ["participant", "status"],
    },
    "Encounter": {
        "allowed": [
            "account", "appointment", "basedOn", "class", "classHistory", "contained",
            "diagnosis", "episodeOfCare", "extension", "hospitalization", "id", "identifier",
            "implicitRules", "language", "length", "location", "meta", "modifierExtension",
            "partOf", "participant", "period", "priority", "reasonCode", "reasonReference",
            "serviceProvider", "serviceType", "status", "statusHistory", "subject", "text",
            "type",
        ],
        "required": ["class", "status"],
    },
    "MedicationRequest": {
        "allowed": [
            "authoredOn", "basedOn", "category", "contained", "courseOfTherapyType",
            "detectedIssue", "dispenseRequest", "doNotPerform", "dosageInstruction",
            "encounter", "eventHistory", "extension", "groupIdentifier", "id", "identifier",
            "implicitRules", "instantiatesCanonical", "instantiatesUri", "insurance", "intent",
            "language", "medication[x]", "meta", "modifierExtension", "note", "performer",
            "performerType", "priorPrescription", "priority", "reasonCode", "reasonReference",
            "recorder", "reported[x]", "requester", "status", "statusReason", "subject",
            "substitution", "supportingInformation", "text",
        ],
        "required": ["intent", "medication[x]", "status", "subject"],
    },
}

# Choice elements: the JSON key is the element name with the "[x]" replaced by
# the type of the selected variant.
CHOICE_VARIANTS = {
    "deceased[x]": ["deceasedBoolean", "deceasedDateTime"],
    "multipleBirth[x]": ["multipleBirthBoolean", "multipleBirthInteger"],
    "medication[x]": ["medicationCodeableConcept", "medicationReference"],
    "reported[x]": ["reportedBoolean", "reportedReference"],
}

# Elements this project's own profile requires on top of the R4 base.
PROFILE_REQUIRED = {
    "Patient": ["identifier", "name"],
    "Practitioner": ["name", "qualification"],
    "Encounter": ["subject", "participant", "appointment"],
    "MedicationRequest": ["encounter", "requester"],
    "Appointment": [],
    "Slot": [],
    "Schedule": [],
}

# --------------------------------------------------------------------------
# Terminology declared by docs/fhir-mappings.md section 8
# --------------------------------------------------------------------------

ADMINISTRATIVE_GENDER = {
    "http://hl7.org/fhir/administrative-gender": {"male", "female", "other", "unknown"},
}
APPOINTMENT_STATUS = {
    "http://hl7.org/fhir/appointmentstatus": {
        "proposed", "pending", "booked", "arrived", "fulfilled", "cancelled", "noshow",
        "entered-in-error", "checked-in", "waitlist",
    },
}
PARTICIPATION_STATUS = {
    "http://hl7.org/fhir/participationstatus": {"accepted", "declined", "tentative", "needs-action"},
}
PARTICIPANT_REQUIRED = {
    "http://hl7.org/fhir/participantrequired": {"required", "optional", "information-only"},
}
ENCOUNTER_STATUS = {
    "http://hl7.org/fhir/encounter-status": {
        "planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled",
        "entered-in-error", "unknown",
    },
}
ENCOUNTER_CLASS = {
    "http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode": {"AMB"},
}
ENCOUNTER_TYPE = {
    "http://terminology.hl7.org/CodeSystem/v3-ActCode": {"VR"},
}
MEDICATION_REQUEST_STATUS = {
    "http://hl7.org/fhir/medicationrequest-status": {
        "active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft",
        "unknown",
    },
}
MEDICATION_REQUEST_INTENT = {
    "http://hl7.org/fhir/CodeSystem/medicationrequest-intent": {
        "proposal", "plan", "order", "original-order", "reflex-order", "filler-order",
        "instance-order", "option",
    },
}
SLOT_STATUS = {
    "http://hl7.org/fhir/slotstatus": {
        "free", "busy", "busy-unavailable", "busy-tentative", "entered-in-error",
    },
}
PARTICIPANT_TYPE = {
    "http://terminology.hl7.org/CodeSystem/v3-ParticipationType": {
        "SBJ", "PPR", "ATND", "SPRF", "PART", "PPRF",
    },
}

# Identifier systems this project declares (docs/fhir-mappings.md section 2.1)
# plus the two R4 standard systems used for identifier types.
ALLOWED_IDENTIFIER_SYSTEMS = {
    "https://telemedicine.example.org/identifier/mrn",
    "https://telemedicine.example.org/identifier/license",
    "https://telemedicine.example.org/identifier/appointment",
    "https://telemedicine.example.org/identifier/encounter",
    "https://telemedicine.example.org/identifier/prescription",
    "https://telemedicine.example.org/identifier/slot",
    "https://telemedicine.example.org/identifier/schedule",
    "http://hl7.org/fhir/sid/us-npi",
    "http://terminology.hl7.org/CodeSystem/v2-0203",
}

# Extensions this project declares (docs/fhir-mappings.md section 2.4)
ALLOWED_EXTENSIONS = {
    "https://telemedicine.example.org/fhir/StructureDefinition/encounter-clinical-note",
}

CANONICAL_BASE = "https://telemedicine.example.org/fhir/"

# Reference target types that may appear in the examples.
KNOWN_TARGET_TYPES = set(PROFILES) | {"Condition", "Organization", "ServiceRequest", "Location"}

# --------------------------------------------------------------------------
# Lexical forms
# --------------------------------------------------------------------------

ID_RE = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
REFERENCE_RE = re.compile(r"^(?:urn:uuid:)?[A-Z][A-Za-z]*/[A-Za-z0-9\-.]{1,64}$|^#[A-Za-z0-9\-.]{1,64}$")


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)):
        return len(value) == 0
    return False


def _check_code(errors, path, system, code, value_set, label):
    """Check a code against a value set keyed by its code system."""
    if system is None or code is None:
        errors.append(f"{path}: {label} has no coding.system/code")
        return
    allowed = value_set.get(system)
    if allowed is None:
        errors.append(f"{path}: {label} uses code system '{system}', which the mapping does not declare")
        return
    if code not in allowed:
        errors.append(f"{path}: {label} code '{code}' is not in the declared value set for {system}")


def _check_coding(errors, path, coding, value_set, label):
    if not isinstance(coding, dict):
        errors.append(f"{path}: {label} is not a Coding")
        return
    _check_code(errors, path, coding.get("system"), coding.get("code"), value_set, label)


def _check_codeable_concept(errors, path, concept, value_set, label):
    if not isinstance(concept, dict):
        errors.append(f"{path}: {label} is not a CodeableConcept")
        return
    codings = concept.get("coding")
    if codings is None:
        # A CodeableConcept with only `text` is valid (e.g. an example-bound
        # element the project does not code).
        return
    if not isinstance(codings, list) or not codings:
        errors.append(f"{path}: {label}.coding must be a non-empty array")
        return
    for index, coding in enumerate(codings):
        _check_coding(errors, f"{path}.coding[{index}]", coding, value_set, label)


def _check_reference(errors, path, reference, example_ids, allow_local=True):
    if not isinstance(reference, str):
        errors.append(f"{path}: reference must be a string")
        return
    if reference.startswith("#"):
        if not allow_local:
            errors.append(f"{path}: local references are not allowed here")
        return
    if not REFERENCE_RE.match(reference):
        errors.append(f"{path}: '{reference}' is not a valid FHIR reference")
        return
    target = reference.split("/")[-1]
    resource_type = reference.split("/")[-2].replace("urn:uuid:", "")
    if resource_type in example_ids and target not in example_ids[resource_type]:
        errors.append(
            f"{path}: reference to {resource_type}/{target} does not resolve to any example resource"
        )


def _check_identifier(errors, path, identifier):
    if not isinstance(identifier, dict):
        errors.append(f"{path}: Identifier must be an object")
        return
    system = identifier.get("system")
    if system is not None and system not in ALLOWED_IDENTIFIER_SYSTEMS:
        errors.append(f"{path}: identifier system '{system}' is not declared by the mapping")
    if "value" not in identifier and "type" not in identifier:
        errors.append(f"{path}: Identifier needs a value or a type")


def _check_instant(errors, path, value, pattern, label):
    if not isinstance(value, str) or not pattern.match(value):
        errors.append(f"{path}: '{value}' is not a valid {label}")


def _check_extension(errors, path, extension):
    if not isinstance(extension, dict):
        errors.append(f"{path}: Extension must be an object")
        return
    url = extension.get("url")
    if url not in ALLOWED_EXTENSIONS:
        errors.append(f"{path}: extension url '{url}' is not declared by the mapping")
    value_keys = [key for key in extension if key.startswith("value")]
    if len(value_keys) != 1:
        errors.append(f"{path}: Extension must carry exactly one value[x] element, found {value_keys}")


def _check_participant(errors, path, participant, example_ids, require_status=True):
    """Check a participant.

    ``Appointment.participant`` requires ``status`` (ParticipationStatus) and
    ``required`` (ParticipantRequired). ``Encounter.participant`` has neither in
    R4 — it only has ``type``, ``period`` and ``individual`` — so the caller
    decides which rule set applies.
    """
    if not isinstance(participant, dict):
        errors.append(f"{path}: participant must be an object")
        return
    if require_status:
        status = participant.get("status")
        if status is None:
            errors.append(f"{path}.status: required by R4 (ParticipationStatus) but missing")
        else:
            _check_code(errors, f"{path}.status", "http://hl7.org/fhir/participationstatus",
                        status, PARTICIPATION_STATUS, "participant.status")
        required = participant.get("required")
        if required is None:
            errors.append(f"{path}.required: required by R4 (ParticipantRequired) but missing")
        else:
            _check_code(errors, f"{path}.required", "http://hl7.org/fhir/participantrequired",
                        required, PARTICIPANT_REQUIRED, "participant.required")
    types = participant.get("type")
    if types is not None:
        if not isinstance(types, list) or not types:
            errors.append(f"{path}.type: must be a non-empty array of CodeableConcept")
        else:
            for index, concept in enumerate(types):
                _check_codeable_concept(
                    errors, f"{path}.type[{index}]", concept, PARTICIPANT_TYPE,
                    "participant.type",
                )
    actor = participant.get("actor") or participant.get("individual")
    if actor is None:
        errors.append(f"{path}: participant needs an actor/individual reference")
    else:
        _check_reference(errors, f"{path}.actor", actor.get("reference"), example_ids)


def validate_resource(resource, example_ids, source):
    """Return a list of validation errors for one resource."""
    errors = []
    if not isinstance(resource, dict):
        return [f"{source}: resource must be a JSON object"]

    resource_type = resource.get("resourceType")
    if resource_type not in PROFILES:
        return [f"{source}: resourceType '{resource_type}' is not one of the modelled resources"]

    profile = PROFILES[resource_type]
    allowed = set(profile["allowed"]) | {"resourceType"}
    for choice, variants in CHOICE_VARIANTS.items():
        allowed.discard(choice)
        allowed.update(variants)

    for key in resource:
        if key not in allowed:
            errors.append(f"{source}: element '{key}' is not part of the R4 {resource_type} resource")

    for key in profile["required"]:
        if key in CHOICE_VARIANTS:
            present = any(variant in resource for variant in CHOICE_VARIANTS[key])
        else:
            present = not _is_empty(resource.get(key))
        if not present:
            errors.append(f"{source}: '{key}' is required by the R4 {resource_type} definition but missing")
    for key in PROFILE_REQUIRED.get(resource_type, []):
        if _is_empty(resource.get(key)):
            errors.append(f"{source}: '{key}' is required by the telemedicine profile but missing")

    resource_id = resource.get("id")
    if resource_id is not None and (not isinstance(resource_id, str) or not ID_RE.match(resource_id)):
        errors.append(f"{source}: 'id' must match [A-Za-z0-9\\-.]{1,64}")

    meta = resource.get("meta")
    if isinstance(meta, dict):
        for profile_url in meta.get("profile", []) or []:
            if not isinstance(profile_url, str) or not profile_url.startswith(CANONICAL_BASE):
                errors.append(f"{source}: meta.profile '{profile_url}' is not under {CANONICAL_BASE}")
        if "lastUpdated" in meta:
            _check_instant(errors, f"{source}.meta.lastUpdated", meta["lastUpdated"],
                           DATETIME_RE, "dateTime")

    for index, identifier in enumerate(resource.get("identifier", []) or []):
        _check_identifier(errors, f"{source}.identifier[{index}]", identifier)

    for index, extension in enumerate(resource.get("extension", []) or []):
        _check_extension(errors, f"{source}.extension[{index}]", extension)

    if resource_type in ("Patient", "Practitioner"):
        gender = resource.get("gender")
        if gender is None:
            errors.append(f"{source}.gender: required by the administrative-gender binding")
        else:
            _check_code(errors, f"{source}.gender", "http://hl7.org/fhir/administrative-gender",
                        gender, ADMINISTRATIVE_GENDER, "gender")
        birth_date = resource.get("birthDate")
        if birth_date is not None:
            _check_instant(errors, f"{source}.birthDate", birth_date, DATE_RE, "date")

    if resource_type == "Schedule":
        actors = resource.get("actor") or []
        if not isinstance(actors, list) or not actors:
            errors.append(f"{source}.actor: must be a non-empty array of references")
        else:
            for index, actor in enumerate(actors):
                _check_reference(errors, f"{source}.actor[{index}]", actor.get("reference"),
                                 example_ids)

    if resource_type == "Slot":
        status = resource.get("status")
        if status is not None:
            _check_code(errors, f"{source}.status", "http://hl7.org/fhir/slotstatus", status,
                        SLOT_STATUS, "Slot.status")
        for key in ("start", "end"):
            if key in resource:
                _check_instant(errors, f"{source}.{key}", resource[key], INSTANT_RE, "instant")
        if "schedule" in resource:
            _check_reference(errors, f"{source}.schedule",
                             resource["schedule"].get("reference"), example_ids)
        start, end = resource.get("start"), resource.get("end")
        if isinstance(start, str) and isinstance(end, str) and start >= end:
            errors.append(f"{source}: Slot end '{end}' is not after start '{start}'")

    if resource_type == "Appointment":
        status = resource.get("status")
        if status is not None:
            _check_code(errors, f"{source}.status", "http://hl7.org/fhir/appointmentstatus", status,
                        APPOINTMENT_STATUS, "Appointment.status")
        for key in ("start", "end"):
            if key in resource:
                _check_instant(errors, f"{source}.{key}", resource[key], INSTANT_RE, "instant")
        start, end = resource.get("start"), resource.get("end")
        if isinstance(start, str) and isinstance(end, str) and start >= end:
            errors.append(f"{source}: Appointment end '{end}' is not after start '{start}'")
        minutes = resource.get("minutesDuration")
        if minutes is not None and (not isinstance(minutes, int) or minutes <= 0):
            errors.append(f"{source}.minutesDuration: must be a positive integer")
        participants = resource.get("participant") or []
        if not isinstance(participants, list) or not participants:
            errors.append(f"{source}.participant: must contain at least one participant")
        else:
            for index, participant in enumerate(participants):
                _check_participant(errors, f"{source}.participant[{index}]", participant,
                                   example_ids)
        for index, slot in enumerate(resource.get("slot", []) or []):
            _check_reference(errors, f"{source}.slot[{index}]", slot.get("reference"),
                             example_ids)
        if "created" in resource:
            _check_instant(errors, f"{source}.created", resource["created"], DATETIME_RE, "dateTime")

    if resource_type == "Encounter":
        status = resource.get("status")
        if status is not None:
            _check_code(errors, f"{source}.status", "http://hl7.org/fhir/encounter-status", status,
                        ENCOUNTER_STATUS, "Encounter.status")
        encounter_class = resource.get("class")
        if encounter_class is not None:
            _check_coding(errors, f"{source}.class", encounter_class, ENCOUNTER_CLASS,
                          "Encounter.class")
        for index, concept in enumerate(resource.get("type", []) or []):
            _check_codeable_concept(errors, f"{source}.type[{index}]", concept, ENCOUNTER_TYPE,
                                    "Encounter.type")
        if "subject" in resource:
            _check_reference(errors, f"{source}.subject", resource["subject"].get("reference"),
                             example_ids)
        for index, appointment in enumerate(resource.get("appointment", []) or []):
            _check_reference(errors, f"{source}.appointment[{index}]",
                             appointment.get("reference"), example_ids)
        for index, participant in enumerate(resource.get("participant", []) or []):
            _check_participant(errors, f"{source}.participant[{index}]", participant, example_ids,
                               require_status=False)
        period = resource.get("period")
        if isinstance(period, dict):
            for key in ("start", "end"):
                if key in period:
                    _check_instant(errors, f"{source}.period.{key}", period[key], INSTANT_RE,
                                   "instant")
            start, end = period.get("start"), period.get("end")
            if isinstance(start, str) and isinstance(end, str) and end < start:
                errors.append(f"{source}.period: end '{end}' is before start '{start}'")

    if resource_type == "MedicationRequest":
        status = resource.get("status")
        if status is not None:
            _check_code(errors, f"{source}.status", "http://hl7.org/fhir/medicationrequest-status",
                        status, MEDICATION_REQUEST_STATUS, "MedicationRequest.status")
        intent = resource.get("intent")
        if intent is not None:
            _check_code(errors, f"{source}.intent",
                        "http://hl7.org/fhir/CodeSystem/medicationrequest-intent", intent,
                        MEDICATION_REQUEST_INTENT, "MedicationRequest.intent")
        medication = resource.get("medicationCodeableConcept")
        if medication is None:
            if "medicationReference" not in resource:
                errors.append(f"{source}: medication[x] is required (1..1) but missing")
        else:
            codings = medication.get("coding") or []
            if not codings:
                errors.append(f"{source}.medicationCodeableConcept: must carry at least one coding")
            for index, coding in enumerate(codings):
                if not isinstance(coding, dict) or not coding.get("system"):
                    errors.append(f"{source}.medicationCodeableConcept.coding[{index}]: "
                                  "missing coding.system")
        for key in ("subject", "requester", "encounter"):
            if key in resource:
                _check_reference(errors, f"{source}.{key}", resource[key].get("reference"),
                                 example_ids)
        if "authoredOn" in resource:
            _check_instant(errors, f"{source}.authoredOn", resource["authoredOn"], DATETIME_RE,
                           "dateTime")
        dosages = resource.get("dosageInstruction") or []
        if not isinstance(dosages, list):
            errors.append(f"{source}.dosageInstruction: must be an array")
        else:
            for index, dosage in enumerate(dosages):
                if not isinstance(dosage, dict):
                    errors.append(f"{source}.dosageInstruction[{index}]: must be an object")
                    continue
                if not dosage.get("text"):
                    errors.append(f"{source}.dosageInstruction[{index}].text: "
                                  "required by the telemedicine profile")
                timing = dosage.get("timing")
                if isinstance(timing, dict):
                    repeat = timing.get("repeat")
                    if isinstance(repeat, dict):
                        bounds = repeat.get("boundsDuration")
                        if isinstance(bounds, dict) and not isinstance(bounds.get("value"), (int, float)):
                            errors.append(f"{source}.dosageInstruction[{index}].timing.repeat."
                                          "boundsDuration.value: must be a number")
        dispense = resource.get("dispenseRequest")
        if isinstance(dispense, dict):
            repeats = dispense.get("numberOfRepeatsAllowed")
            if repeats is not None and (not isinstance(repeats, int) or repeats < 0):
                errors.append(f"{source}.dispenseRequest.numberOfRepeatsAllowed: "
                              "must be a non-negative integer")

    return errors


def load_examples(directory: Path):
    """Load every JSON example in a directory, keyed by file name."""
    resources = {}
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            resources[path.name] = json.load(handle)
    return resources


def build_example_index(resources):
    """Map resource type -> set of example ids, for reference resolution."""
    index = {}
    for resource in resources.values():
        if isinstance(resource, dict):
            index.setdefault(resource.get("resourceType"), set()).add(resource.get("id"))
    return index


def validate_directory(directory: Path):
    resources = load_examples(directory)
    if not resources:
        return [f"{directory}: no example resources found"], {}
    example_ids = build_example_index(resources)
    errors = []
    for name, resource in resources.items():
        errors.extend(validate_resource(resource, example_ids, name))
    return errors, resources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_dir = Path(__file__).resolve().parent.parent / "docs" / "fhir" / "examples"
    parser.add_argument("directory", nargs="?", type=Path, default=default_dir,
                        help="directory holding the example resources")
    parser.add_argument("--json", action="store_true", help="emit the result as JSON")
    args = parser.parse_args(argv)

    errors, resources = validate_directory(args.directory)

    if args.json:
        print(json.dumps({
            "directory": str(args.directory),
            "resources": sorted(resources),
            "errors": errors,
            "valid": not errors,
        }, indent=2))
        return 1 if errors else 0

    print(f"Checked {len(resources)} example resources in {args.directory}")
    for name in sorted(resources):
        resource = resources[name]
        print(f"  {name}: {resource.get('resourceType')}/{resource.get('id')}")
    if errors:
        print(f"\n{len(errors)} problem(s) found:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nAll example resources satisfy the declared ENG-001 mapping rules.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

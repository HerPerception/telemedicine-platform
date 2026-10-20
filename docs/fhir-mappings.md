# FHIR R4 resource mappings

- **Feature:** `ENG-001` — data model and FHIR R4 resource mappings
- **FHIR version:** R4 (4.0.1)
- **Status:** Implemented, pending review. No API exists yet; this document specifies the mapping the
  ENG-006 API layer will implement, and the example resources under
  [`fhir/examples/`](fhir/examples/) are the mapping's reference instances.
- **Owner:** `OpenCode-20261019-b07bb18a`

## 1. How this mapping was verified

On 2026-10-19 the published R4 StructureDefinitions for the five core resources were downloaded from
the HL7 specification server and their element names, cardinalities, datatypes and value-set
bindings were extracted and compared with the tables below:

| Resource | Canonical definition used for verification |
| --- | --- |
| `Patient` | `https://hl7.org/fhir/R4/patient.profile.json` (id `Patient`, version 4.0.1) |
| `Practitioner` | `https://hl7.org/fhir/R4/practitioner.profile.json` (id `Practitioner`, version 4.0.1) |
| `Appointment` | `https://hl7.org/fhir/R4/appointment.profile.json` (id `Appointment`, version 4.0.1) |
| `Encounter` | `https://hl7.org/fhir/R4/encounter.profile.json` (id `Encounter`, version 4.0.1) |
| `MedicationRequest` | `https://hl7.org/fhir/R4/medicationrequest.profile.json` (id `MedicationRequest`, version 4.0.1) |

Every element path, cardinality and code listed in this document was read from those definitions
rather than from memory. The R4 files are not vendored into this repository; the URLs above are the
source of truth and are re-checkable at any time.

The value sets and code systems in §8 were verified the same way, from the published R4 artifacts
`https://hl7.org/fhir/R4/valueset-<name>.json` and
`https://hl7.org/fhir/R4/codesystem-<name>.json`, plus the v3 code systems
`http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode` and
`http://terminology.hl7.org/CodeSystem/v3-ActCode` (the latter was checked for the `VR` and `AMB`
codes). The R4 `encounter-participant-type` value set and the R4 `appointment-example` were also
read, which is where the participant type codes in §5 come from.

**What this mapping is not.** It is not a conformance claim. Full R4 validation (profile
conformance, terminology server expansion, invariant evaluation) is ENG-006 work. The examples in
this feature are checked by `scripts/validate_fhir_examples.py`, which verifies the subset of rules
declared in this document — required elements, cardinalities, the code systems used, identifier and
date formats, and reference resolution — and is documented as such.

## 2. Conventions

### 2.1 Identifiers and code systems

| Purpose | System URI | Notes |
| --- | --- | --- |
| Patient business identifier | `https://telemedicine.example.org/identifier/mrn` | `Patient.identifier[0].value` = `patient.mrn` |
| Practitioner NPI | `http://hl7.org/fhir/sid/us-npi` | Used only when `practitioner.npi` is present |
| Appointment identifier | `https://telemedicine.example.org/identifier/appointment` | Value = the appointment id |
| Encounter identifier | `https://telemedicine.example.org/identifier/encounter` | Value = the encounter id |
| Prescription identifier | `https://telemedicine.example.org/identifier/prescription` | Value = the medication request id |
| Medication catalogue (local) | `https://telemedicine.example.org/CodeSystem/medication` | See §7 open item 1 |

`https://telemedicine.example.org` is a placeholder for the deployment's canonical base URL. It
must be replaced by the real base URL before ENG-006 ships; the values are recorded here so the
change is a single, deliberate edit.

### 2.2 References and identifiers

- `Resource.id` is the string form of the row's UUID primary key, which satisfies the FHIR `id`
  regex `[A-Za-z0-9\-\.]{1,64}`.
- References are relative (`Patient/<id>`, `Appointment/<id>`) in REST payloads, as R4 allows, and
  `urn:uuid:` style is accepted by the validator for bundle-relative documents.
- The resource `id` and the business identifier are separate: the id is internal, the identifier is
  what a patient or an external system quotes.

### 2.3 Profile base

The API is expected to serve profiles derived from the R4 base resources:

```
https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-patient
https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-practitioner
https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-appointment
https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-encounter
https://telemedicine.example.org/fhir/StructureDefinition/telemedicine-medicationrequest
```

The profiles are declared in ENG-006. The mapping below is what those profiles will constrain.

### 2.4 One declared extension

R4 `Encounter` has no free-text note element, and the MVP needs to record a clinical note. Rather
than distorting an existing element, the note is carried in one extension:

| Extension URL | Value type | Used on | Meaning |
| --- | --- | --- | --- |
| `https://telemedicine.example.org/fhir/StructureDefinition/encounter-clinical-note` | `valueString` | `Encounter` | The clinician's free-text note for the visit |

`Encounter.reasonCode.text` carries the patient's presenting complaint, which is a coded reason
rather than a note, so it is not reused for this purpose.

## 3. Patient

Source: `patient` table. Target: `Patient` (R4 4.0.1).

| FHIR path | Cardinality in R4 | Source | Notes |
| --- | --- | --- | --- |
| `Patient.id` | 0..1 | `patient.id` | UUID string |
| `Patient.meta.lastUpdated` | 0..1 | `patient.updated_at` | |
| `Patient.identifier` | 0..* | `patient.mrn` | One `Identifier`, `system` per §2.1, `use = usual` |
| `Patient.active` | 0..1 | — | Not stored; the MVP has no deactivation state. Omitted |
| `Patient.name` | 0..* | `patient.family_name`, `patient.given_names` | One `HumanName`, `use = official`, `family` + `given[]` |
| `Patient.telecom` | 0..* | `patient.phone`, `patient.email` | One `ContactPoint` per populated value, `system = phone` / `email` |
| `Patient.gender` | 0..1 | `patient.gender` | Bound *required* to `administrative-gender`; always sent, `unknown` when not disclosed |
| `Patient.birthDate` | 0..1 | `patient.birth_date` | `date` |
| `Patient.address` | 0..* | `patient.address_*` | One `Address` when any address part is present |
| `Patient.generalPractitioner` | 0..* | — | Not populated: the MVP is a single-clinician practice |
| `Patient.contact` | 0..* | — | Not modelled; a caregiver contact is out of the MVP scope |

`Patient` has no required elements in R4. This profile nevertheless requires `identifier` and
`name`, because a patient without a business identifier or a name is not usable by the product.

## 4. Practitioner

Source: `practitioner` table. Target: `Practitioner` (R4 4.0.1).

| FHIR path | Cardinality in R4 | Source | Notes |
| --- | --- | --- | --- |
| `Practitioner.id` | 0..1 | `practitioner.id` | |
| `Practitioner.meta.lastUpdated` | 0..1 | `practitioner.updated_at` | |
| `Practitioner.identifier` | 0..* | `practitioner.npi` | `system = http://hl7.org/fhir/sid/us-npi` when present |
| `Practitioner.active` | 0..1 | — | Not stored; omitted |
| `Practitioner.name` | 0..* | `practitioner.family_name`, `given_names`, `credentials` | One `HumanName`, `family`, `given[]`, `suffix[]` = credentials |
| `Practitioner.telecom` | 0..* | — | Not stored in ENG-001; the practice contact details live in the account record (ENG-002) |
| `Practitioner.gender` | 0..1 | `practitioner.gender` | Bound *required* to `administrative-gender`; always sent |
| `Practitioner.qualification` | 0..* | `practitioner.license_number`, `license_region`, `specialty` | One entry when a licence is on file: `identifier.value` = licence number, `issuer` = a display-only `Reference` carrying the region, `code.text` = specialty. The R4 `qualification.code` element is *example*-bound to `v2-0360/2.7`; a free-text `code.text` is used because the MVP has no qualification code system |
| `Practitioner.photo` | 0..* | — | Not stored; omitted |

`Practitioner` has no required elements in R4; this profile requires `name` and `qualification`.

## 5. Appointment

Source: `appointment` table. Target: `Appointment` (R4 4.0.1).

| FHIR path | Cardinality in R4 | Source | Notes |
| --- | --- | --- | --- |
| `Appointment.id` | 0..1 | `appointment.id` | |
| `Appointment.meta.lastUpdated` | 0..1 | `appointment.updated_at` | |
| `Appointment.identifier` | 0..* | `appointment.id` | One `Identifier`, system per §2.1 |
| `Appointment.status` | **1..1** | `appointment.status` | Bound *required* to `appointmentstatus` |
| `Appointment.cancelationReason` | 0..1 | `appointment.cancellation_reason` | `text`; sent when the appointment was cancelled |
| `Appointment.serviceCategory` | 0..* | — | Not populated; the MVP has one service type |
| `Appointment.specialty` | 0..* | `practitioner.specialty` | Optional; `preferred` binding `c80-practice-codes` is not met by a free-text specialty, so the element is omitted unless a coded value is available |
| `Appointment.reasonCode` | 0..* | `appointment.reason_code`, `reason_text` | One `CodeableConcept` carrying `text` only. The `encounter-reason` value set is bound *preferred* and is defined over SNOMED CT; the MVP has no SNOMED licence, so no `coding` is emitted. See §8.1 |
| `Appointment.description` | 0..1 | — | Derived display text, e.g. "Telemedicine consultation"; not stored |
| `Appointment.start` | 0..1 | `appointment.starts_at` | `instant` — UTC with explicit offset |
| `Appointment.end` | 0..1 | `appointment.ends_at` | `instant` |
| `Appointment.minutesDuration` | 0..1 | `appointment.duration_minutes` | `positiveInt`; must equal the window length |
| `Appointment.slot` | 0..* | `appointment.slot_id` | Reference to the `Slot` resource. A cancelled appointment keeps this reference, so the FHIR record still shows which window was booked and released, while the slot may be booked again |
| `Appointment.created` | 0..1 | `appointment.created_at` | `dateTime` |
| `Appointment.comment` | 0..1 | `appointment.patient_note` | |
| `Appointment.patientInstruction` | 0..1 | — | Not stored; ENG-003 may reuse `patient_note` for this |
| `Appointment.participant` | **1..\*** | `appointment.patient_id`, `appointment.practitioner_id` | Two participants, see below |

`Appointment.participant` is required (1..\*) in R4, and each participant requires `status`:

| Participant | `type` | `actor` | `status` | `required` |
| --- | --- | --- | --- | --- |
| Patient | `http://terminology.hl7.org/CodeSystem/v3-ParticipationType` code `SBJ` (subject) | `Patient/<id>` | `accepted` | `required` |
| Practitioner | same system, code `PPR` (primary performer) | `Practitioner/<id>` | `accepted` | `required` |

`participant.type` is bound *extensible* to `encounter-participant-type`, and `participant.required`
and `participant.status` are bound *required* to `participantrequired` and `participationstatus`.
The v3 codes are used as in the R4 `appointment-example`, where the practitioner participant carries
`v3-ParticipationType` `ATND` — the same pattern, with `PPR`/`SBJ` chosen because they state the
role more precisely. An *extensible* binding permits codes from the bound code system that the value
set does not itself include.

The MVP has a single clinician, so a second practitioner participant is not modelled; ENG-004's
waiting-room admission is expressed by the `status` value changing between `needs-action` and
`accepted`, not by adding participants.

## 6. Encounter

Source: `encounter` table. Target: `Encounter` (R4 4.0.1).

| FHIR path | Cardinality in R4 | Source | Notes |
| --- | --- | --- | --- |
| `Encounter.id` | 0..1 | `encounter.id` | |
| `Encounter.meta.lastUpdated` | 0..1 | `encounter.updated_at` | |
| `Encounter.identifier` | 0..* | `encounter.id` | One `Identifier`, system per §2.1 |
| `Encounter.status` | **1..1** | `encounter.status` | Bound *required* to `encounter-status` |
| `Encounter.class` | **1..1** | `encounter.encounter_class` | `Coding`, `system = http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode`, `code = AMB` (ambulatory) |
| `Encounter.type` | 0..* | `encounter.encounter_type` | `CodeableConcept`, `system = http://terminology.hl7.org/CodeSystem/v3-ActCode`, `code = VR` (virtual). The `encounter-type` binding is *example* strength and R4's own code system does not describe a virtual modality, so the v3 code is used |
| `Encounter.subject` | 0..1 | `encounter.patient_id` | Reference to `Patient`. R4 makes it optional; this profile requires it |
| `Encounter.participant` | 0..* | `encounter.practitioner_id` | One participant, `individual` = `Practitioner/<id>`, `type` = v3 ParticipationType `PPR` |
| `Encounter.appointment` | 0..* | `encounter.appointment_id` | Reference to `Appointment` |
| `Encounter.period` | 0..1 | `encounter.started_at`, `ended_at` | `Period`; `end` omitted while the encounter is open |
| `Encounter.reasonCode` | 0..* | `encounter.reason_code`, `chief_complaint` | One `CodeableConcept` carrying `text` only (`chief_complaint`). The `encounter-reason` value set is SNOMED CT and *preferred*-bound; see §8.1 |
| `Encounter.extension` | 0..* | `encounter.clinical_note` | The single declared extension (§2.4) |
| `Encounter.diagnosis` | 0..* | — | Not modelled: a diagnosis is a `Condition` reference and `Condition` is outside the five core resources (open item 5 in the data model) |

## 7. MedicationRequest

Source: `medication_request` table. Target: `MedicationRequest` (R4 4.0.1).

| FHIR path | Cardinality in R4 | Source | Notes |
| --- | --- | --- | --- |
| `MedicationRequest.id` | 0..1 | `medication_request.id` | |
| `MedicationRequest.meta.lastUpdated` | 0..1 | `medication_request.updated_at` | |
| `MedicationRequest.identifier` | 0..* | `medication_request.id` | One `Identifier`, system per §2.1 |
| `MedicationRequest.status` | **1..1** | `medication_request.status` | Bound *required* to `medicationrequest-status` |
| `MedicationRequest.intent` | **1..1** | `medication_request.intent` | Bound *required* to `medicationrequest-intent`; `order` by default |
| `MedicationRequest.category` | 0..* | — | Not populated; `medicationrequest-category` is *example*-bound |
| `MedicationRequest.medication[x]` | **1..1** | `medication_request.medication_system`, `medication_code`, `medication_display` | Sent as `medicationCodeableConcept` with one `Coding` |
| `MedicationRequest.subject` | **1..1** | `medication_request.patient_id` | Reference to `Patient` |
| `MedicationRequest.encounter` | 0..1 | `medication_request.encounter_id` | Reference to `Encounter`; this profile requires it |
| `MedicationRequest.authoredOn` | 0..1 | `medication_request.authored_on` | `dateTime` |
| `MedicationRequest.requester` | 0..1 | `medication_request.prescriber_id` | Reference to `Practitioner`; this profile requires it, and the requester must be the encounter's practitioner |
| `MedicationRequest.note` | 0..* | `medication_request.notes` | One `Annotation`, `text` |
| `MedicationRequest.dosageInstruction` | 0..* | `dosage_text`, `dose_quantity`, `dose_unit`, `route_text`, `duration_days` | See below |
| `MedicationRequest.dispenseRequest` | 0..1 | `refills`, `dispense_quantity` | `numberOfRepeatsAllowed`, `quantity` |

`medication[x]` is required (1..1) and is a choice of `CodeableConcept` or `Reference`. This
implementation uses `medicationCodeableConcept`; the reference form would point at a `Medication`
resource, which the MVP does not have (there is no medication catalogue resource, only a local code
system).

`dosageInstruction` breakdown:

| FHIR path | Source | Notes |
| --- | --- | --- |
| `dosageInstruction[0].text` | `dosage_text` | Required by this profile; prose directions |
| `dosageInstruction[0].route.text` | `route_text` | Route is *example*-bound; a free-text route is used |
| `dosageInstruction[0].doseAndRate[0].doseQuantity` | `dose_quantity`, `dose_unit` | `Quantity` with UCUM unit |
| `dosageInstruction[0].timing.repeat.boundsDuration` | `duration_days` | `Duration`, e.g. `10 days` |

### Medication terminology — open item

The MVP has no pharmacy or eRx integration (explicitly out of scope in the README) and ENG-001 has
no verified drug terminology to draw on. Rather than assert RxNorm codes that have not been checked
against the terminology server, `medicationCodeableConcept` uses the local code system
`https://telemedicine.example.org/CodeSystem/medication`. OPS-001 must confirm whether the target
jurisdiction requires a national drug code before any real prescription is issued.

## 8. Value sets and code systems used

The R4 value sets are *composed* from FHIR's own code systems. The table below lists the value set,
the code system the codes come from, the binding strength declared in the R4 StructureDefinition,
and the codes this MVP uses. The code systems and their code lists were read from the published R4
CodeSystem definitions on 2026-10-19.

| Element | Value set | Code system | Binding in R4 | Codes used by the MVP |
| --- | --- | --- | --- | --- |
| `Patient.gender`, `Practitioner.gender` | `administrative-gender` | `http://hl7.org/fhir/administrative-gender` | required | `male`, `female`, `other`, `unknown` |
| `Appointment.status` | `appointmentstatus` | `http://hl7.org/fhir/appointmentstatus` | required | `booked`, `arrived`, `fulfilled`, `cancelled`, `noshow` (the remaining codes of the code system are permitted by the model) |
| `Appointment.participant.status` | `participationstatus` | `http://hl7.org/fhir/participationstatus` | required | `accepted`, `needs-action` |
| `Appointment.participant.required` | `participantrequired` | `http://hl7.org/fhir/participantrequired` | required | `required` |
| `Encounter.status` | `encounter-status` | `http://hl7.org/fhir/encounter-status` | required | `planned`, `arrived`, `in-progress`, `finished`, `cancelled` |
| `Encounter.class` | `v3-ActEncounterCode` | `http://terminology.hl7.org/CodeSystem/v3-ActEncounterCode` | extensible | `AMB` |
| `Encounter.type` | `encounter-type` | `http://terminology.hl7.org/CodeSystem/v3-ActCode` | example | `VR` |
| `MedicationRequest.status` | `medicationrequest-status` | `http://hl7.org/fhir/medicationrequest-status` | required | `active`, `completed`, `cancelled`, `stopped` |
| `MedicationRequest.intent` | `medicationrequest-intent` | `http://hl7.org/fhir/CodeSystem/medicationrequest-intent` | required | `order` |
| `MedicationRequest.priority` | `request-priority` | `http://hl7.org/fhir/ValueSet/request-priority` | required | Not populated by the MVP |
| `Appointment.participant.type`, `Encounter.participant.type` | `encounter-participant-type` | `http://terminology.hl7.org/CodeSystem/v3-ParticipationType` | extensible | `SBJ` (patient), `PPR` (practitioner) |
| `Appointment.reasonCode`, `Encounter.reasonCode` | `encounter-reason` | `http://snomed.info/sct` | preferred | No `coding` emitted — see §8.1 |

The validator in `scripts/validate_fhir_examples.py` checks the example resources against the code
lists above.

### 8.1 Why the reason codes carry text only

The R4 `encounter-reason` value set is composed entirely from SNOMED CT filters, and it is bound
*preferred* rather than *required*. Emitting a `coding` from that value set requires a SNOMED CT
licence, which this project does not have, and inventing a code outside the value set would not
satisfy the binding either. `Appointment.reasonCode` and `Encounter.reasonCode` therefore carry
`text` only, which is valid for an extensible/preferred binding. The `reason_code` columns in the
database model hold the place where a coded value will go once OPS-001 settles the terminology
source.

The same reasoning applies to `MedicationRequest.medicationCodeableConcept` (§7).

## 9. Deviations from the plain R4 base

| Deviation | Resource | Reason |
| --- | --- | --- |
| `Patient.identifier` and `Patient.name` are required | `Patient` | R4 requires neither; the product cannot use a patient without them |
| `Practitioner.name` and `Practitioner.qualification` are required | `Practitioner` | Same reason |
| `Encounter.subject` and `Encounter.participant` are required | `Encounter` | R4 makes them optional; a telemedicine encounter always has a patient and a clinician |
| `Encounter.appointment` is required | `Encounter` | The MVP records the encounter of a booked visit |
| `MedicationRequest.encounter` and `MedicationRequest.requester` are required | `MedicationRequest` | A prescription must be tied to an encounter and to the treating clinician, per the README acceptance criteria |
| `Encounter.extension` `…/encounter-clinical-note` | `Encounter` | R4 `Encounter` has no free-text note element |
| `Appointment.specialty` omitted | `Appointment` | The stored specialty is free text and cannot satisfy the `c80-practice-codes` *preferred* binding |

## 10. Example resources

[`fhir/examples/`](fhir/examples/) contains one example of each modelled resource. The five core
resources are cross-referenced by id, and the two supporting resources (`Schedule` and `Slot`) close
the appointment chain:

| File | Resource | Id used in the examples |
| --- | --- | --- |
| `patient.json` | `Patient` | `1f3c9a20-6b1e-4c2f-9a44-0d5b6c7e8f91` |
| `practitioner.json` | `Practitioner` | `7d2e4b31-8c3a-4d5e-8b6f-1e2d3c4b5a60` |
| `schedule.json` | `Schedule` | `6e9f0a1b-7c8d-4e5f-9a6b-7c8d9e0f1a2b` |
| `slot.json` | `Slot` | `5d8e9f0a-6b7c-4d4e-8f5a-6b7c8d9e0f1a` |
| `appointment.json` | `Appointment` | `2a5b6c7d-9e4f-4a1b-8c2d-3e4f5a6b7c8d` |
| `encounter.json` | `Encounter` | `3b6c7d8e-4f5a-4b2c-9d3e-4f5a6b7c8d9e` |
| `medicationrequest.json` | `MedicationRequest` | `4c7d8e9f-5a6b-4c3d-8e4f-5a6b7c8d9e0f` |

`Schedule` and `Slot` are not part of the five core resources and ENG-006 does not expose them as
endpoints, but `Slot.schedule` is required in R4 and `Appointment.slot` points at a `Slot`, so both
are modelled and exemplified.

Validate them with:

```bash
python3 scripts/validate_fhir_examples.py
python3 -m unittest discover -s tests -v
```

The validator checks the declared subset of R4 rules described in §1. It is not a FHIR validator:
it does not expand terminology or evaluate FHIRPath invariants.

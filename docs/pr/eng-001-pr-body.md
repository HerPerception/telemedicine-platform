# ENG-001: define the data model and FHIR R4 resource mappings

## Problem

The MVP scope in `README.md` is defined, but nothing is built. The appointment, video,
e-prescription and FHIR API features all depend on one thing that does not exist yet: a shared
data model with a defined mapping onto FHIR R4. Without it, each feature invents its own shape for
patients, practitioners, bookings and prescriptions, and the FHIR API cannot be built afterwards
without a migration.

This PR adds that foundation. It is the first item on the README roadmap.

## What this changes

New, no existing file is modified.

- **`docs/data-model.md`** — the six clinical entities (`patient`, `practitioner`,
  `schedule_slot`, `appointment`, `encounter`, `medication_request`), their relationships, the
  invariants the database enforces, cross-cutting rules (UTC storage plus a separate IANA zone for
  rendering, business identifiers vs internal keys, least data, auditability) and six open items
  with their owners.
- **`docs/fhir-mappings.md`** — the field-level mapping onto FHIR R4 (4.0.1) for `Patient`,
  `Practitioner`, `Appointment`, `Encounter` and `MedicationRequest`, plus the supporting `Schedule`
  and `Slot`. It records the identifier and code-system conventions, one declared extension
  (`Encounter` has no free-text note element in R4), the value sets used, and the deliberate
  deviations from the plain R4 base.
- **`db/schema.sql`** — PostgreSQL 13+ DDL for the six tables.
- **`docs/fhir/examples/`** — one example of each modelled resource, cross-referenced by id.
- **`scripts/validate_fhir_examples.py`** — a dependency-free validator for the subset of R4 rules
  the mapping declares.
- **`tests/test_fhir_examples.py`**, **`tests/test_schema.py`** — `unittest` suites.
- **`AGENTS.md`** — bootstrap agent guidance, listing only commands that have been verified.
- **`.gitignore`** — Python bytecode and virtualenv entries.

## Resulting behaviour

Double-booking is impossible at the storage layer, not just in application code:

- a GiST exclusion constraint rejects two overlapping slots for the same practitioner;
- `appointment.slot_id` is unique, so a slot backs at most one appointment;
- a composite foreign key forces the appointment's practitioner and window to match the slot's;
- composite foreign keys similarly force the encounter's patient and practitioner to match the
  appointment's, and the prescription's patient and prescriber to match the encounter's.

Clinical rows are never cascade-deleted, and every foreign key uses `ON DELETE RESTRICT`.

## How the FHIR mapping was verified

Every element name, cardinality, datatype, binding and code in the mapping was read from the
published HL7 artifacts on 2026-10-19 rather than from memory:

- `https://hl7.org/fhir/R4/{patient,practitioner,schedule,slot,appointment,encounter,medicationrequest}.profile.json`
- `https://hl7.org/fhir/R4/valueset-*.json` and `codesystem-*.json` for the value sets and code lists
- `https://hl7.org/fhir/R4/{patient,practitioner,appointment,encounter}-example.json` for the official example patterns
- `http://terminology.hl7.org/CodeSystem/v3-ActCode` for the `VR` and `AMB` codes

Two findings changed the design during the work: R4's `MedicationRequest.intent` uses
`instance-order`/`option` (not R5's `administering-order`), and the `encounter-reason` value set is
SNOMED CT only. Because the project has no SNOMED licence, reason codes are carried as `text` and no
drug code was invented — both are recorded as open items owned by OPS-001.

## Validation

```bash
python3 scripts/validate_fhir_examples.py   # 7 resources checked, 0 problems
python3 -m unittest discover -s tests -v     # 40 tests, OK
```

Both commands were run in the worktree and passed.

**Not validated:** `db/schema.sql` was never executed. There is no PostgreSQL server available in the
development environment (no `psql`, and the Docker socket is not accessible to the user), so the DDL
is reviewed and structurally tested only. It must be applied to a real instance before any
application depends on it. No CI is configured for this repository yet, so there is no CI result to
report.

## Acceptance criteria

- [x] Documented entities for Patient, Practitioner, Appointment, Encounter and MedicationRequest
      (plus the supporting Schedule and Slot) — `docs/data-model.md`.
- [x] Documented mappings for the same resources — `docs/fhir-mappings.md`.
- [x] Reviewed against FHIR R4 — verified against the published R4 4.0.1 definitions, code systems
      and value sets; the method and the source URLs are in the mapping document.
- [x] Invariants that the later features depend on are enforced by the schema, not only by prose.
- [ ] DDL executed against a real PostgreSQL instance — blocked here, no server available.
- [ ] README roadmap checkbox ticked — left for the integrator, because `README.md` carries
      uncommitted work from `DOC-001`.

## Remaining gates and follow-ups

- OPS-001 owns the terminology decisions: SNOMED reason codes and the medication catalogue. Until
  then the local code system is used for medications and no unverified code is asserted.
- ENG-002 (auth, authz, audit) depends on this model and on the `account_ref` columns it defines.
  The clinical tables here should not be re-shaped without recording a change in `resolution.md`.
- ENG-006 owns full profile conformance, terminology expansion and FHIRPath invariant evaluation.
  The validator in this PR is explicitly not a FHIR validator and says so.
- The `https://telemedicine.example.org` base URL used in identifiers, profile URLs and the
  extension is a placeholder and must be replaced with the deployment's canonical base URL.

## Deployment and migration notes

No migration is applied by this PR — the schema file is new and unused. Applying it creates six
tables and requires `btree_gist` (`CREATE EXTENSION IF NOT EXISTS btree_gist`, already in the file)
and PostgreSQL 13+ for `gen_random_uuid()`. There is nothing to roll back while no application
uses these tables.

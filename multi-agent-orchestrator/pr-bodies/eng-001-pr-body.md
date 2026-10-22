# ENG-001: define the data model and FHIR R4 resource mappings

Adds the core data model for the telemedicine MVP and its mapping onto
FHIR R4 (4.0.1). This is the first implementation prerequisite for the
booking, video, prescription and FHIR API features.

* docs/data-model.md - six clinical entities (patient, practitioner,
  schedule_slot, appointment, encounter, medication_request), their
  relationships, database-enforced invariants, and open items with owners.
* docs/fhir-mappings.md - field-level mapping for Patient, Practitioner,
  Appointment, Encounter and MedicationRequest, plus the supporting Schedule
  and Slot. Every element, cardinality and code was verified against the
  published R4 StructureDefinitions, CodeSystems and ValueSets rather than
  from memory.
* db/schema.sql - PostgreSQL 13+ DDL. Overlapping slots for one
  practitioner are rejected by a GiST exclusion constraint, appointment.
  slot_id is unique, and composite foreign keys keep the appointment
  window, encounter and prescription consistent with their parents.
* docs/fhir/examples/ - one example of each modelled resource, plus a
  dependency-free validator and unittest suites.
* docs/pr/eng-001-pr-body.md - the PR description for the integrator.

No application code, build system or CI exists yet, so the only runnable
checks are the validator and the test suite:

    python3 scripts/validate_fhir_examples.py
    python3 -m unittest discover -s tests -v

The DDL has not been executed: no PostgreSQL server was available in the
development environment.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

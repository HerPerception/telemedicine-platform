# ENG-005: e-prescription issuance, the document, download and the lifecycle

A patient must be able to download and print a prescription, and the
document that leaves the system must be trustworthy.

* telemedicine/prescriptions.py - PrescriptionService, the document store
  and a PDF renderer with no third-party dependency. The renderer writes a
  minimal, well-formed PDF 1.4 file, and the result is checked with an
  external tool: poppler's pdftotext extracts the medication, the
  directions, the patient and the prescriber from the generated file, and
  Ghostscript renders it without an error.
* The document states the prescription id, when it was issued, the status
  it was issued with, the patient, the prescriber, the medication and the
  directions. It is a snapshot: a later status change does not rewrite it,
  and the schema refuses an UPDATE on the document row, because a printed
  prescription must not be able to change afterwards.
* Every document is stored with the SHA-256 of its bytes. A download that
  does not match its checksum is refused rather than served, and the
  refusal is audited.
* The prescription lifecycle (draft, active, on-hold, completed, cancelled,
  stopped) moves along explicit transitions. Only the clinician who issued
  a prescription may change it; a patient may read and download their own
  but may not change one.
* db/prescription_schema.sql - the document metadata, with a foreign key to
  medication_request and a trigger that refuses an UPDATE.
* docs/prescription-design.md - the design, the rendering evidence and the
  gaps that remain.
* tests/test_prescriptions.py, tests/test_prescription_schema.py.

Amendments to earlier features, recorded in the design document and in the
coordination log: one authorization rule for changing a prescription,
PractitionerRecord and the prescription status write path in
telemedicine/records.py, and the audit entry of a successful issue now
identifies the prescription rather than the encounter.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

The DDL has not been executed: no PostgreSQL server was available in the
development environment.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

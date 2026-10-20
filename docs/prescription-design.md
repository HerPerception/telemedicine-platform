# E-prescription design

- **Feature:** `ENG-005` — implement e-prescription issuance, viewing, download, and audit
- **Status:** Implemented and tested. The document store is in-memory; the schema for it is in
  [`db/prescription_schema.sql`](../db/prescription_schema.sql) and has **not** been executed (no
  PostgreSQL server is available in the development environment).
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. Acceptance criteria

The backlog item is: *"prescription tied to encounter and patient; only the treating clinician can
issue; create/read audit entries exist."* The README adds: *"every create/read is audit-logged; the
document renders correctly when downloaded."*

| Criterion | Where | Evidence |
| --- | --- | --- |
| Tied to the encounter and the patient | `telemedicine/records.py` — the prescription inherits the encounter's patient and prescriber | `tests/test_prescriptions.py::IssuingTest::test_the_prescription_is_tied_to_the_encounter_and_the_patient` |
| Only the treating clinician may issue | The rule table: `MedicationRequest` + `create` + scope `treating` | `::IssuingTest::test_a_patient_cannot_issue_a_prescription`, `::test_a_clinician_who_did_not_treat_the_patient_cannot_issue` |
| Create and read are audit-logged | ENG-002's records service, extended here | `::IssuingTest::test_issuing_is_audited`, `::test_a_refused_issue_is_audited` |
| The document renders correctly | `telemedicine/prescriptions.py` — a PDF renderer with no third-party dependency | `::DocumentTest::test_the_document_renders_in_a_real_pdf_reader` (checked with poppler's `pdftotext`) |

## 2. What a prescription is

A prescription is issued **during or after a consultation**, against an `Encounter`. It is not a free
floating order:

- it carries the encounter it belongs to;
- it inherits the patient and the prescriber **from that encounter**, so a prescription can never be
  attached to a different patient or a different clinician than the visit it was issued during — the
  same pairing the database enforces with a composite foreign key
  (`medication_request_encounter_match`);
- it states the medication (code, display name and catalogue), the directions, and when it was
  authored.

The medication comes from a **local catalogue**
(`https://telemedicine.example.org/CodeSystem/medication`). The MVP has no pharmacy integration,
and asserting a national drug code that has not been checked against a terminology server would be
worse than a local code with an honest name. OPS-001 owns the decision on the terminology source.

## 3. Issuing

`PrescriptionService.issue(actor, encounter_id, ...)` delegates to the records service of ENG-002,
which authorizes and audits, and then renders the document.

The audit entry of a successful issue identifies **the prescription that was created**. A refused
attempt identifies the encounter, because no prescription exists to point at; both entries name the
encounter in their detail. (This changed the behaviour of ENG-002, which recorded the encounter id
for both outcomes — see §7.)

## 4. The document

The patient must be able to download and print a prescription, so the document is rendered as a
**PDF**.

### 4.1 The renderer

`render_pdf(lines)` writes a minimal, well-formed PDF 1.4 file: a catalog, a page tree, one page,
one content stream, and the Helvetica font, with a cross-reference table and a trailer. Text is
written uncompressed, which keeps the file readable and lets a test assert on its contents.

The renderer exists because the project has no third-party dependency and the document is simple
enough that a PDF library would be the larger risk: a hand-written file can be checked byte by byte,
and it is checked by an external tool (§4.3).

Characters that the WinAnsi encoding cannot represent are replaced rather than written raw, and
parentheses and backslashes are escaped, so a medication name with a bracket in it cannot break the
file.

### 4.2 What the document says

The document states the prescription id, when it was issued, the status it was issued with, the
patient, the prescriber (with their identifier), the medication, the medication code and catalogue,
and the directions. It says plainly that it is the record of the prescription issued during the
consultation, and that it is issued to the patient named above only.

**The document is a snapshot.** A later status change does not rewrite it, and the schema refuses an
`UPDATE` on the document row. A prescription that has been printed and handed to a pharmacy must not
be able to change afterwards; the current status is in the prescription record, and the document
says what it said when it was issued.

### 4.3 That it renders

The renderer writes the file, so the only way to know the file is readable is to read it with
something else. In the development environment:

- `pdfinfo` parses it: 1 page, A4, PDF 1.4;
- `pdftotext` extracts the full text, including the medication, the directions, the patient and the
  prescriber;
- Ghostscript renders it without an error.

`tests/test_prescriptions.py::DocumentTest::test_the_document_renders_in_a_real_pdf_reader` runs
`pdftotext` over a generated document and asserts on the extracted text. It is skipped when
`pdftotext` is not installed, so the suite still runs on a machine without poppler — but the
rendering evidence in this repository was produced with it.

## 5. Integrity

Every document is stored with the SHA-256 of its bytes. A download that does not match its
checksum is **refused**, not served, and the refusal is audited with the outcome `error`. This is
the same rule the `prescription_document.checksum` column supports in the database.

## 6. The lifecycle

A prescription is not edited in place. It moves through a small, explicit set of states:

```
draft ──▶ active ──▶ on-hold ──▶ active
             │  │        └──────▶ stopped
             │  ├───────▶ completed   (final)
             │  └───────▶ cancelled   (final)
             └──────────▶ cancelled   (final)
```

- Only the clinician who issued it may change it, and only along an allowed transition. A patient
  may read and download their own prescriptions but may not change one.
- A completed, cancelled or stopped prescription is final. Moving out of it is refused and audited.
- Cancelling needs a reason.
- Every change is audited with the action `prescription.status_change`.

The statuses are the R4 `MedicationRequestStatus` code set, and the transitions are a subset of what
FHIR allows, restricted to what a single-clinician practice needs.

## 7. Amendments to earlier features

Recorded in `multi-agent-orchestrator/resolution.md` and in §6 above.

| File | Amendment | Why |
| --- | --- | --- |
| `telemedicine/authorization.py` | One rule added: `Practitioner` + `medication_request` + `update`, scope `treating` | The prescription lifecycle needs a write path that only the treating clinician may use. The rules stay fail-closed |
| `telemedicine/records.py` | `PractitionerRecord` and `add_practitioner` added; `get_prescription` and `update_prescription_status` added; the audit entry of a successful issue now identifies the prescription rather than the encounter | The document states who prescribed the medication, so the service needs the clinician's record; the lifecycle needs a write path; and an audit entry for a create should point at the thing that was created |
| `tests/test_authorization.py` | The assertion about the resource id of a prescription-create entry was updated to match | It followed the behaviour change above |

## 8. Known gaps

1. **No object store.** The document bytes live in memory. A deployment needs encrypted object
   storage; the schema models the metadata and a `storage_key` for it, but nothing fills that in.
2. **No encryption.** Encryption at rest and the key management around it are OPS-001 work. The
   document is a health record and must not be stored unencrypted in a deployment.
3. **No pharmacy integration.** Out of scope by the README, and it is why the medication catalogue
   is local.
4. **The document has no signature.** A printed prescription cannot be verified as genuine. For a
   practice where a pharmacist must trust it, that matters; a signature is out of scope here and
   should be an OPS-001 decision.
5. **One document per prescription, forever.** A change to the directions after issue is not
   possible — the prescription would have to be cancelled and reissued. That is the correct
   behaviour for a legal document, but the MVP has no "reissue" flow.
6. **No multilingual or accessible rendering.** The PDF uses Helvetica at a fixed size. A
   prescription that a patient with a visual impairment cannot read is a compliance problem; WCAG
   does not apply to a PDF in the same way, but the content should be offered in an accessible form
   too, which ENG-006 can do.
7. **The store is not durable.** A restart loses the documents. The `prescription_document` table
   is the answer, and it has never been applied to a database.

## 9. What the later features need

- **ENG-006** (FHIR API) must serve `MedicationRequest` with the R4 mappings of ENG-001, and the
  download as a binary response with the `application/pdf` content type, behind the same
  authorization.
- **OPS-001** must settle the medication terminology, the encryption of the document store, and
  whether a signature is required.
- The audit trail of a prescription — who issued it, who read it, who downloaded it, and every
  status change — is already in the tamper-evident log and needs no further work.

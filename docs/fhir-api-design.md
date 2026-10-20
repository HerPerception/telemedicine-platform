# FHIR R4 API design

- **Feature:** `ENG-006` — expose the FHIR R4 API
- **Status:** Implemented and tested. The API runs on the standard library's
  `http.server`; the data behind it is the in-memory application layer, not a database.
- **Owner:** `OpenCode-20261020-3dafd2c8`

## 1. Acceptance criteria

The backlog item is: *"the five core resources are readable/writable with auth; responses validate
against R4 profiles; unauthorized access returns the correct errors."*

| Criterion | Where | Evidence |
| --- | --- | --- |
| The five resources are readable | `telemedicine/fhir/server.py` — `GET` on the type and on an id | `tests/test_fhir_api.py::ReadTest` (9 tests) |
| The five resources are writable | `POST` for Appointment, Encounter and MedicationRequest; `PUT` for all five | `tests/test_fhir_api.py::WriteTest` (11 tests) |
| With auth | Every request except the metadata needs a session token; the domain services authorize each call | `tests/test_fhir_api.py::AuthenticationTest` |
| Responses validate against R4 profiles | `telemedicine/fhir/validation.py` — every resource is checked before it is sent | `::ReadTest::test_a_patient_reads_their_own_record` and the serialization suite |
| Unauthorized access returns the correct errors | 401, 403, 404, 405, 409, 400, 500, each with an `OperationOutcome` | `::AuthenticationTest`, `::ReadTest`, `::WriteTest` |

## 2. The endpoints

The API is served under `/fhir`.

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/fhir/metadata` | The `CapabilityStatement`. Public, because it describes the server and nothing else |
| `GET` | `/fhir/{Type}` | A search: a `Bundle` of the resources the caller may see |
| `GET` | `/fhir/{Type}/{id}` | One resource |
| `POST` | `/fhir/{Type}` | Creates an Appointment, an Encounter or a MedicationRequest |
| `PUT` | `/fhir/{Type}/{id}` | Updates a resource |
| `DELETE` | `/fhir/{Type}/{id}` | **405.** A clinical record is never deleted; a cancellation is a status, and the record stays |

`{Type}` is one of `Patient`, `Practitioner`, `Appointment`, `Encounter`, `MedicationRequest`.

The resources are the ones of the mapping in [`fhir-mappings.md`](fhir-mappings.md), which is the
contract this API implements: the same identifiers, the same code systems, the same extensions.

### 2.1 What each write does

| Resource | `POST` | `PUT` |
| --- | --- | --- |
| Patient | not supported | The patient updates their own demographics |
| Practitioner | not supported | The practitioner updates their own details |
| Appointment | Books the slot named in `Appointment.slot` | Moves the appointment to another slot, or cancels it |
| Encounter | Records the encounter of the appointment it references | Changes its status, its end time or its clinical note |
| MedicationRequest | Issues the prescription against the encounter it references | Changes its status, or its details |

A `Patient` and a `Practitioner` are created by the practice, not through the API, so there is no
`POST` for them. A patient record without a name would not satisfy the profile, and a practitioner
record without a qualification would not either — the API refuses to serve such a record rather than
sending something that breaks the published profile.

## 3. Authentication and authorization

**Authentication** is the session token of ENG-002, carried in an `Authorization: Bearer <token>`
header. A missing, unknown, expired or revoked token is a **401**, with a `WWW-Authenticate`
header. The token is the same one the browser session would use; there is no OAuth2, and no SMART
on FHIR — see §7.

**Authorization** is not the API's own business. Every call goes through the domain services of
ENG-002, which decide whether the caller may do it and write the audit entry. The API never reads
a record without going through them, so there is exactly one place where the rules live and exactly
one place where the audit trail is written.

The consequences are the ones the rules already imply:

- a patient reads their own record and nobody else's;
- a practitioner reads the record of a patient they treat, and of no other patient — the
  relationship comes from an appointment or an encounter, not from a flag;
- a prescription is issued only by the clinician who treated the encounter, and can be changed only
  by them;
- a patient may not change a prescription, and may not change another person's record.

## 4. The errors

Every error is an `OperationOutcome` with a severity, a code and a diagnostic. The codes are the
FHIR issue types.

| Status | When | Issue code |
| --- | --- | --- |
| `400` | The body is not valid JSON, is not a FHIR resource, is of the wrong type, or carries a change the domain refuses (a cancellation without a reason, for instance) | `invalid` |
| `401` | No session, or a session that is not valid | `login` |
| `403` | The caller is known, but may not do that | `forbidden` |
| `404` | No such resource, or no such endpoint | `not-found` |
| `405` | The method is not supported here, including `DELETE` | `not-supported` |
| `409` | The request conflicts with the state of the data, such as booking a slot that has just been taken | `conflict` |
| `500` | The server produced a resource that does not satisfy the profile — a defect, not a client error | `exception` |

`409` needed a new error type: booking a slot that has just been taken is a conflict with the
current state, not a malformed request. `ConflictError` was added in `telemedicine/errors.py` for
that, and the booking service raises it.

The distinction between `404` and `403` is deliberate and worth stating: the API answers `404` when
it does not know the resource, and `403` when it knows it and the caller may not have it. A patient
asking for a resource that exists but is not theirs gets `403`, which tells them the id is real.
That is a small leak of information, and it is the behaviour the rules imply; if that matters for
the deployment, the two can be merged, and it is a one-line change.

## 5. The responses are checked before they are sent

The API does not merely *try* to produce valid resources. Every resource it is about to send is
checked against the R4 element tables, the cardinalities and the code systems of
`telemedicine/fhir/validation.py` — the same module that checks the examples of ENG-001. A resource
that fails the check is **not sent**: the API answers `500` with the diagnostics instead. The
mapping is therefore a promise the code keeps, not a document that can drift.

The check covers the subset of R4 the project declares. It is not a general FHIR validator: it does
not expand terminology and does not evaluate FHIRPath invariants. That is stated in the module, in
this document and in the validator's own docstring.

## 6. Amendments to earlier features

Recorded in `multi-agent-orchestrator/resolution.md`.

| File | Amendment | Why |
| --- | --- | --- |
| `telemedicine/fhir/validation.py` (new), `scripts/validate_fhir_examples.py` | The R4 tables and the checker moved from the script into the package, so the API and the command-line tool check against one implementation. The script is now a thin front end | The API has to validate what it sends with the same rules the examples are checked with |
| `telemedicine/records.py` | The patient, practitioner, appointment, encounter and prescription records gained the fields that ENG-001's schema defines and the FHIR mapping projects (name parts, gender, contact details, licence, reason, note, dose). Added `read_practitioner_record`, `update_patient`, `update_practitioner`, `create_encounter`, `update_encounter`, `update_prescription`, the list helpers and `patients_treated_by` / `practitioners_treating` | The API cannot expose a field the model does not hold, and the write paths need to be authorized and audited like the read paths |
| `telemedicine/authorization.py` | Three rules: a patient may update their own record, a practitioner their own, and a practitioner the encounter they delivered | The write paths need rules that fail closed |
| `telemedicine/errors.py` | `ConflictError` | A booking that races another one is a conflict, not a malformed request |
| `telemedicine/booking.py` | The two double-booking refusals raise `ConflictError` | So that the API can answer `409` |
| `telemedicine/prescriptions.py` | `issue` passes the extra details through | The API sets the note and the dispense quantities |

## 7. Known gaps

> The open findings of the OPS-001 review, and the conditions for handling real patient
> data, are in [`reviews/compliance-review.md`](reviews/compliance-review.md). This section
> lists the gaps the feature itself knows about; the review ranks them and says which of
> them block a deployment.



1. **No persistence.** The API serves the in-memory application layer. The data is lost when the
   process ends, and the repositories are the ones ENG-002 left in memory.
2. **No TLS.** The server speaks plain HTTP. A deployment must terminate TLS in front of it, and
   the session token must never travel in the clear.
3. **No OAuth2, no SMART on FHIR.** The session token is the mechanism. A FHIR client that expects
   SMART scopes cannot talk to this API, and the mapping of roles onto FHIR capabilities is not
   done. This is a real gap for interoperability, and it is the first thing ENG-006's successor
   should close.
4. **No CORS, no API documentation, no OpenAPI.** The API is not usable from a browser
   application on another origin, and there is no machine-readable description of it beyond the
   `CapabilityStatement`.
5. **The search is a list, not a query.** `GET /fhir/Patient` returns everything the caller may
   see. There are no search parameters, no `_id`, no `_lastUpdated`, no pagination, no
   `_include`/`_revinclude` and no `Bundle` transaction. The `CapabilityStatement` declares no
   search parameters either, so the server does not advertise what it does not do.
6. **No conditional create or update.** `If-Match`, `If-None-Match` and `If-Modified-Since` are
   ignored, so a client cannot make a read-modify-write safe against a concurrent change.
7. **No request logging.** The audit log records every access to a record, which is what matters
   for the compliance gates, but the HTTP layer keeps no access log.
8. **No rate limiting** on the API, and the same missing lockout policy as ENG-002.
9. **The server is a development server.** `http.server` is not built for the public internet; a
   deployment needs a real server and a reverse proxy.

## 8. Running it

```python
from telemedicine.auth import AuthService
from telemedicine.booking import BookingService, SlotService
from telemedicine.fhir.repository import FhirRepository
from telemedicine.fhir.server import FhirApplication, serve
from telemedicine.prescriptions import PrescriptionService
from telemedicine.records import RecordsService

records = RecordsService()
slots = SlotService()
booking = BookingService(slots, records=records)
prescriptions = PrescriptionService(records)
auth = AuthService()

application = FhirApplication(FhirRepository(records, booking, prescriptions), auth)
serve(application, host="127.0.0.1", port=8080)
```

A request then looks like:

```bash
curl -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/fhir+json" \
     http://127.0.0.1:8080/fhir/Patient/patient-1
```

## 9. What is left for the successor

- **QA-001** — the test suite is now 269 tests, but there is still no CI, and not every acceptance
  criterion of the README has a test of its own. This API's tests are the largest block of it.
- **OPS-001** — the compliance review has to look at the gaps in §7, especially TLS, SMART, the
  missing lockout and the audit retention.
- **ENG-004** — the video rooms are the last unread part of the visit loop, and the appointment
  window that the booking service produces is what a room would admit the two parties against.
- A database, a real HTTP server, a session store and a deployment are all still ahead of this.

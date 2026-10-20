# Privacy, security, accessibility and regulatory review

- **Feature:** `OPS-001` — privacy, security, accessibility, and regulatory review
- **Reviewed state:** `52bd552` (the ENG-006 tip) — the whole feature set: the data model, the
  security layer, booking, prescriptions and the FHIR API
- **Reviewer:** `OpenCode-20261020-3dafd2c8`
- **Date:** 2026-10-20
- **Verdict:** **not signed off.** Real patient data must not be used until the conditions in §8 are
  met. Two findings were closed in this branch; the rest are listed with their remediation.

## 1. What was reviewed, and how

**Reviewed.** Every path in the repository that handles health data or decides who may see it:

- the three schema files (`db/schema.sql`, `db/auth_schema.sql`, `db/prescription_schema.sql`) and
  what they make possible;
- the application layer: `auth`, `authorization`, `audit`, `records`, `booking`, `prescriptions`;
- the FHIR layer: `validation`, `serialization`, `repository`, `server`;
- the 269 tests, as evidence of what is actually enforced.

**Method.** A threat-oriented read of each path, from the outside in: what an attacker, a curious
user, an accidental user or a regulator would find. Each finding below was checked against the code
before it was written down, and each states the evidence it rests on. Where a finding was cheap and
safe to close, it was closed in this branch and has a test.

**Not reviewed — and not reviewable yet.**

- **Penetration testing.** No external tester, and no environment to test: there is no deployment.
- **The parts of the product that do not exist**: the browser client, the video room, the deployment,
  the database, the mail transport, the object store, the identity provider.
- **The deployment platform, the repository settings and branch protection, the backup and restore
  procedure** — none of it exists.
- **Dependency review** — there are no third-party dependencies, which is the whole of that review.
- **Performance and load**, and the behaviour of the audit log at volume.

**A limitation of this review.** It was carried out by the same agent that wrote the code. That is
a real weakness: the reviewer knows where to look, and does not know what a stranger would try. The
findings below should be treated as the ones a careful reading found, not as the ones that exist.
An independent review is a condition of sign-off (§8).

## 2. Summary

| Area | Critical | High | Medium | Low | Fixed here |
| --- | --- | --- | --- | --- | --- |
| Privacy | 0 | 3 | 4 | 1 | 1 |
| Security | 0 | 3 | 6 | 5 | 3 |
| Accessibility | 0 | 1 | 2 | 1 | 0 |
| Regulatory | 1 | 3 | 5 | 2 | 0 |
| **Total** | **1** | **10** | **17** | **9** | **4** |

The single critical finding is REG-01: **the jurisdiction is not established**, and until it is,
no regulatory conclusion can be drawn at all.

## 3. The README's compliance gates, assessed

The README lists six gates for any real deployment. Here is where each stands.

| Gate (README) | Status | Why |
| --- | --- | --- |
| Privacy: consent capture | **Not met** | There is no consent entity, no consent field and no consent flow anywhere in the model (PRIV-02) |
| Privacy: minimum-necessary data access | **Partly met** | Access is scoped by role and by the treatment relationship, and every access is audited, but the API returns the whole patient record to anyone who may read it (PRIV-06) |
| Privacy: a documented retention policy | **Not met** | Nothing is ever purged, and no policy exists (PRIV-03) |
| Security: TLS in transit | **Not met** | The API speaks plain HTTP (SEC-05) |
| Security: encryption at rest | **Not met** | There is no storage at all; the prescription documents are in memory (PRIV-05 in §4) |
| Security: strong authentication | **Partly met** | Passwords are hashed with PBKDF2 at 600 000 iterations and sessions are token-based, but there is no lockout, no MFA and no breach-resistant store (SEC-04, SEC-12) |
| Security: role-based authorization | **Met for what exists** | The rule table is explicit and fail-closed, and every path goes through it; the API adds no path of its own |
| Auditability: tamper-evident logs | **Partly met** | The log is a hash chain and refuses to extend a broken chain, but it lives in memory and is not anchored anywhere (SEC-06, SEC-07) |
| Reliability: backups, restore testing, a recovery procedure | **Not met** | There is no database and no backup (OPS-002) |
| Accessibility: WCAG 2.1 AA for booking and consultation | **Not met — not assessable** | There is no user interface at all (A11Y-01) |
| Regulatory: confirm the rules for the target jurisdiction | **Not met — the jurisdiction is unknown** | (REG-01) |

## 4. Privacy findings

### PRIV-01 — A patient's record could be cached by an intermediary — **fixed in this branch**

**Severity:** High. **Evidence:** `telemedicine/fhir/server.py`, `_json()`, which set only
`Content-Type`. A proxy or a browser could keep a copy of a response holding a patient's record.

**Remediation applied:** every response now carries `Cache-Control: no-store, no-cache,
must-revalidate, private`, `Pragma: no-cache` and `X-Content-Type-Options: nosniff`.
`tests/test_compliance_remediations.py::ResponseHeaderTest` keeps it that way.

### PRIV-02 — No consent is captured — **blocker for sign-off**

**Severity:** High. **Evidence:** there is no consent table in `db/schema.sql`, no consent field on
`patient`, and no consent flow in the application layer. The README names consent capture as a
privacy gate.

**Remediation:** a `patient_consent` table (what was consented to, when, how it was captured, which
version of the notice, and a revocation timestamp) and a capture step in the registration flow.
The notice itself is a legal artefact, not an engineering one, and has to be written and approved
first. **Owner:** the practice, with engineering.

### PRIV-03 — Nothing is ever deleted, and no retention policy exists — **blocker for sign-off**

**Severity:** High. **Evidence:** `db/auth_schema.sql` says "entries are never deleted, so the log
grows without bound"; `db/schema.sql` says "Clinical data is never cascade-deleted"; the
prescription documents are never purged either. There is no policy anywhere that says how long
anything is kept.

**Remediation:** a written retention schedule (what is kept for how long, and what happens at the
end of it), then a purge job that implements it — and, for the audit log, an archive that preserves
the hash chain, or records the hash the archive starts from. **Owner:** the practice, with
engineering.

### PRIV-04 — No route to a data-subject access or erasure request — **blocker for sign-off**

**Severity:** High. **Evidence:** the model deliberately never deletes a clinical record, which is
right for clinical integrity and wrong for an erasure request unless an exemption applies.

**Remediation:** a legal decision on the lawful basis and any exemption (clinical record-keeping
is often one), then either a documented refusal path or a process that anonymises rather than
deletes. **Owner:** the practice, with legal advice. This is not an engineering decision.

### PRIV-05 — The prescription documents are not encrypted at rest

**Severity:** High. **Evidence:** `telemedicine/prescriptions.py` keeps the document bytes in a
`DocumentStore` in memory; `db/prescription_schema.sql` models a `storage_key` for a future object
store and says nothing about encryption.

**Remediation:** encrypted object storage with key management, and a documented key rotation and
recovery procedure. **Owner:** engineering, with the practice's compliance adviser.

### PRIV-06 — A clinician receives the whole patient record

**Severity:** Medium. **Evidence:** `telemedicine/fhir/serialization.py`, `patient_resource()`,
returns the address, phone, email and date of birth to any practitioner who treats the patient. A
consultation rarely needs the home address.

**Remediation:** decide what a clinician actually needs — probably name, contact details and
demographics — and project the rest out of the clinical view, keeping it for the administrative
view. **Owner:** engineering, with the practice.

### PRIV-07 — The status code tells an unauthorised caller that a resource exists

**Severity:** Medium. **Evidence:** `telemedicine/fhir/server.py`, `_read()`, answers `404` for an
unknown id and `403` for one that exists but is not the caller's.

**Remediation:** either answer `404` for both, or accept the difference. The reason it is called
out here is that it is a decision, not an accident: the current behaviour is more useful to a
legitimate client and leaks the existence of an id to an illegitimate one. **Owner:** engineering,
with the practice's adviser.

### PRIV-08 — The audit log holds identifiers, not clinical content — **a strength**

**Evidence:** an entry carries the actor, the action, the resource type and id, the outcome and a
short detail. It holds no name, no address, no medication and no note. A failed login records a
masked address (`a***@example.org`) rather than the real one. This should be preserved by any
change to the log's schema.

### PRIV-09 — The canonical base URL is a placeholder that ships identifiers

**Severity:** Medium. **Evidence:** `https://telemedicine.example.org` appears in the identifier
systems, the profile URLs, the extension URL and the medication code system across
`telemedicine/fhir/serialization.py` and the documentation.

**Remediation:** replace it with the deployment's own base URL, in one place, before anything
identifies a real patient. An identifier that points at a domain the practice does not own is a
problem even if nobody ever resolves it. **Owner:** engineering.

## 5. Security findings

### SEC-01 — The login revealed which addresses were registered — **fixed in this branch**

**Severity:** High. **Evidence:** `telemedicine/auth.py`, `authenticate()`, returned immediately
for an unknown account and ran the PBKDF2 verification (600 000 iterations, roughly a third of a
second) only for a known one. The difference is measurable, so the login form was an account
enumeration oracle.

**Remediation applied:** the unknown-account path now verifies the password against a decoy hash
so that both paths cost the same. `tests/test_compliance_remediations.py::AccountEnumerationTest`
keeps it that way.

### SEC-02 — A password change left the old sessions alive — **fixed in this branch**

**Severity:** Medium. **Evidence:** `telemedicine/auth.py`, `set_password()`, changed the hash and
nothing else; every session issued under the old password stayed valid for the rest of its
eight-hour life.

**Remediation applied:** a password change now ends every session of that account, including the
one it was made with, and the audit entry says how many were ended.
`tests/test_compliance_remediations.py::SessionInvalidationTest` keeps it that way.

### SEC-03 — A refusal explained itself — **fixed in this branch**

**Severity:** Medium. **Evidence:** `telemedicine/fhir/server.py` returned the authorization
reason in the `OperationOutcome` diagnostics — for example "the patient account is not in scope for
this patient" — which tells an unauthorised caller how the rule works and, combined with PRIV-07,
who the record belongs to.

**Remediation applied:** the response now says what happened ("not permitted: read on patient")
and the reason stays in the audit log, which the caller cannot read.
`tests/test_compliance_remediations.py::ResponseHeaderTest` keeps it that way.

### SEC-04 — No lockout and no rate limiting on the login — **blocker for sign-off**

**Severity:** High. **Evidence:** `db/auth_schema.sql` has `failed_attempts` and `locked_until`
columns, and nothing writes them. There is no rate limit anywhere.

**Remediation:** a counter that survives a restart and is shared between instances — a table in the
database, or a rate limiter in front of the API — plus an exponential back-off and an alert on a
burst of failures. Note that the columns alone are not the fix; a counter that lives in one
process is wrong the moment there are two. **Owner:** engineering.

### SEC-05 — No TLS — **blocker for sign-off**

**Severity:** High. **Evidence:** `telemedicine/fhir/server.py` uses `http.server` and speaks plain
HTTP. A session token in an `Authorization` header would travel in the clear.

**Remediation:** terminate TLS in front of the API, set the session cookie or header to be
rejected over plain HTTP, and set `Strict-Transport-Security` once the domain is known.
**Owner:** engineering, with whoever runs the deployment.

### SEC-06 — The audit log is not durable, and a restart loses it

**Severity:** High. **Evidence:** `telemedicine/audit.py` keeps the chain in a tuple in memory. The
log of ENG-002 is the "tamper-evident" answer to the README's auditability gate, and while the
process lives it is exactly that — but a restart empties it, and a restart is not a security event
that anyone would notice.

**Remediation:** the chain must be durable, and the head of it must be recoverable after a crash.
That means the `audit_log` table of ENG-002 becomes the store of record, with the chain head read
inside the same transaction as the insert, under the advisory lock the schema already documents.
**Owner:** engineering. This is a substantial piece of work, and it is the point of the whole audit
design.

### SEC-07 — The audit chain is anchored nowhere outside the store

**Severity:** Medium. **Evidence:** an attacker with write access to the audit log can rewrite the
chain from the point they entered, and `verify_chain()` will report it as intact.

**Remediation:** anchor the chain head somewhere the attacker cannot rewrite — a digest published
periodically to a separate system, a write-once store, or a periodic digest signed by a key that
does not live beside the log. Without this, "tamper-evident" is a property of the code rather than
of the deployment. **Owner:** engineering, with the practice's adviser.

### SEC-08 — No OAuth2 and no SMART on FHIR

**Severity:** Medium. **Evidence:** the API authenticates with the session token of ENG-002 and the
`CapabilityStatement` advertises no SMART capabilities.

**Remediation:** map the two roles onto FHIR capabilities, and either implement SMART on FHIR or
state clearly that the API is a private, first-party interface that no third-party FHIR client may
use. The second is a legitimate choice for a single-clinician practice, but it has to be a choice
rather than an omission. **Owner:** engineering, with the practice.

### SEC-09 — No CORS policy

**Severity:** Medium. **Evidence:** the API sends no `Access-Control-*` header, so a browser
application served from another origin cannot call it.

**Remediation:** an allowlist of the practice's own origins, never `*` together with credentials,
and a decision about whether the API is called from the browser at all — a same-origin deployment
removes the question. **Owner:** engineering.

### SEC-10 — No conditional create or update

**Severity:** Medium. **Evidence:** `If-Match`, `If-None-Match` and `If-Modified-Since` are ignored
by `telemedicine/fhir/server.py`, so a client that reads a record, changes it and writes it back
can silently overwrite a change made in between.

**Remediation:** honour `If-Match` against the resource version, and make the write conditional.
This matters more once the data is shared between a clinician and a patient-facing client.
**Owner:** engineering.

### SEC-11 — The password policy is a floor

**Severity:** Low. **Evidence:** `telemedicine/auth.py` requires twelve characters and forbids the
account's own email address. There is no breached-password screening, no reuse prevention and no
similarity check.

**Remediation:** screening against a breached-password service needs network access the MVP does
not have; it becomes possible when the deployment has a connection. **Owner:** engineering.

### SEC-12 — No multi-factor authentication

**Severity:** Low, but it is a decision and not an omission. **Evidence:** nothing in the code.

**Remediation:** the practice decides whether the jurisdiction or the risk requires it for a
clinician who prescribes. **Owner:** the practice.

### SEC-13 — The session lifetime is a single constant

**Severity:** Low. **Evidence:** `DEFAULT_SESSION_TTL` of eight hours, no idle timeout, no
absolute cap, and no re-authentication for a sensitive action such as issuing a prescription.

**Remediation:** a shorter lifetime for a clinician, an idle timeout, and re-authentication before
a prescription is issued. **Owner:** engineering.

### SEC-14 — No request logging

**Severity:** Low. **Evidence:** the audit log records access to records, not HTTP requests. A
failed login is recorded; a request that 404s is not.

**Remediation:** an access log at the proxy, kept separately from the audit log and with its own
retention. **Owner:** engineering, with whoever runs the deployment.

### SEC-15 — The server is a development server

**Severity:** Low. **Evidence:** `http.server` with `ThreadingHTTPServer`. It is not built for the
public internet, has no request limits and no timeouts.

**Remediation:** a real server behind a reverse proxy, with timeouts and body-size limits.
**Owner:** engineering.

### SEC-16 — The API does not distinguish a FHIR client from any other client

**Severity:** Low. **Evidence:** any HTTP client with a valid token can call the API. That is
acceptable for a first-party API, and it should be stated rather than assumed.

## 6. Accessibility findings

### A11Y-01 — There is no user interface, so the accessibility gate cannot be assessed — **blocker for sign-off**

**Severity:** High. **Evidence:** the repository contains no client. The README's gate is "core
booking and consultation flows meet WCAG 2.1 AA", and neither flow exists.

**Remediation:** build the client, then assess it against WCAG 2.1 AA with assistive technologies
in the loop, and record the result. **Owner:** engineering, with the practice.

### A11Y-02 — The prescription document is not accessible

**Severity:** Medium. **Evidence:** `telemedicine/prescriptions.py` writes an untagged PDF in one
fixed size. A patient with low vision or using a screen reader cannot read it.

**Remediation:** the structured content is already available as a FHIR `MedicationRequest` through
the API of ENG-006, so the client can render an accessible version of exactly the same content —
and should. A tagged PDF is a larger piece of work and can follow. **Owner:** engineering.

### A11Y-03 — The API's errors are English only and thin

**Severity:** Medium. **Evidence:** the `OperationOutcome` carries a code and a short diagnostic.

**Remediation:** the client maps the issue code to a message in the patient's language. The API
side needs nothing. **Owner:** engineering.

### A11Y-04 — Free text is returned unescaped

**Severity:** Low. **Evidence:** the clinical note, the reason and the patient details are returned
as JSON strings. JSON does not need escaping, but the client must not render them as HTML without
escaping.

**Remediation:** guidance for the client, and a check in the client's own tests. **Owner:**
engineering.

## 7. Regulatory findings

### REG-01 — The jurisdiction is not established — **the critical finding, and a blocker for everything else**

**Severity:** Critical. **Evidence:** the README requires confirming "applicable telemedicine,
e-prescription, and health-data rules for the target jurisdiction before handling real patient
data", and the target jurisdiction appears nowhere in the repository.

**Why it is critical:** every other regulatory question is unanswerable without it. Whether the
consultation may happen at all, whether the prescription is valid, which data-protection law
applies, what the retention rules are and what a breach must trigger all depend on where the
practice and the patient are. No engineering work can substitute for this.

**Remediation:** the practice names the jurisdiction, and a qualified professional answers REG-02
to REG-07 against it. **Owner:** the practice. Everything below is contingent on this.

### REG-02 — The medication catalogue is local, so the prescription is not a valid prescription

**Severity:** High. **Evidence:** `telemedicine/prescriptions.py` uses the code system
`https://telemedicine.example.org/CodeSystem/medication` with codes such as `AMOX-500-CAP`. No
national drug terminology is used.

**Why it matters:** a prescription that identifies a medicine with a local, invented code cannot be
dispensed, cannot be checked against an interaction database and cannot be understood by a
pharmacist. The MVP deliberately did not assert RxNorm codes it had not verified, and that was the
right call at the time — but it means the prescription document is not yet a prescription.

**Remediation:** adopt the national drug terminology of the jurisdiction (RxNorm, dm+d, SNOMED
CT or the local equivalent), map the local catalogue onto it, and verify the mapping against a
terminology server rather than by hand. **Owner:** engineering, once REG-01 is answered.

### REG-03 — A prescription is a document, not a transmission

**Severity:** High. **Evidence:** e-prescription network integration is explicitly out of scope in
the README, and `telemedicine/prescriptions.py` produces a PDF.

**Why it matters:** in most jurisdictions a prescription that is not transmitted electronically has
its own requirements — a wet signature, a particular paper, a copy to the patient, a record in a
prescription register.

**Remediation:** decide whether the MVP issues paper prescriptions or electronic ones, and meet the
rules for that choice. **Owner:** the practice, with legal advice.

### REG-04 — Nothing stops a prescription for a controlled substance

**Severity:** High. **Evidence:** there is no drug category, no special-custody rule and no
electronic prescribing for controlled substances anywhere in the model.

**Why it matters:** controlled substances have their own rules almost everywhere, and this MVP
would happily issue one.

**Remediation:** at minimum, refuse to issue a prescription for anything not in the approved
catalogue, and refuse controlled substances outright until the practice has decided how to handle
them. **Owner:** engineering and the practice, together.

### REG-05 — The patient's location is never established

**Severity:** Medium. **Evidence:** the application records no location, of the patient or of the
clinician, and the consultation is a video appointment.

**Why it matters:** telehealth rules commonly depend on where the patient is physically located,
and a practice licensed in one jurisdiction may not treat a patient in another.

**Remediation:** capture the patient's location at the time of the consultation, or record that it
was confirmed, and refuse consultations where the practice may not treat. **Owner:** engineering,
with the practice.

### REG-06 — Nothing says the service is not for emergencies

**Severity:** Medium. **Evidence:** no such statement exists in the product or the documentation.

**Remediation:** a statement in the client, in the terms the patient accepts, and in the
confirmation message. **Owner:** the practice, with engineering.

### REG-07 — No clinical safety process

**Severity:** Medium. **Evidence:** no incident reporting, no adverse-event handling, no review of
the encounter documentation, and no standard for what a clinical note must contain.

**Remediation:** the practice needs a clinical governance process; engineering needs to make the
encounter record support it. **Owner:** the practice.

### REG-08 — If the practice is in the United States: HIPAA has not been addressed

**Severity:** Medium. **Evidence:** no business associate agreement, no risk analysis, no workforce
training record, no access review, no backup and restore of the audit log, no breach procedure,
and no encryption at rest for the documents or the database.

**Remediation:** the full set, in the order the practice's adviser gives. **Owner:** the practice.

### REG-09 — If the practice is in the European Union: GDPR has not been addressed

**Severity:** Medium. **Evidence:** no record of processing activities, no data protection impact
assessment, no recorded lawful basis, no data-subject rights workflow, no sub-processor list, and
no decision about data residency. The eight-hour session lifetime and the indefinite retention of
the audit log both need a justification.

**Remediation:** as above. **Owner:** the practice.

### REG-10 — The single-clinician assumption is a simplification that will be forgotten

**Severity:** Low. **Evidence:** the role table has two roles and no administrator, and the README
describes one clinician. Nothing stops a practice employing staff.

**Remediation:** when that happens, the model needs a third role, delegated access, and the access
review that goes with it. **Owner:** engineering, with the practice.

### REG-11 — No consent to the telehealth consultation itself

**Severity:** Low, and it is part of PRIV-02. **Evidence:** no consent artefact of any kind.

**Remediation:** with PRIV-02. **Owner:** the practice.

## 8. The conditions for sign-off

**No real patient data may be used until all of the following are true.** This is the review's
conclusion, and it is a hard one.

1. **REG-01 is answered.** The jurisdiction is named and a qualified professional has answered
   REG-02 to REG-07 against it. Until then nothing else matters.
2. **PRIV-02 consent capture is implemented**, and the notice has been written and approved.
3. **PRIV-03 and PRIV-04 are decided and implemented**: a written retention schedule, a purge
   process, and a documented position on erasure requests.
4. **SEC-04, SEC-05 and SEC-06 are closed**: a lockout that works across instances, TLS, and an
   audit log that survives a restart.
5. **A11Y-01 is assessed.** A user interface exists and has been assessed against WCAG 2.1 AA.
6. **QA-001 is done.** Every acceptance criterion in the README has a test, and CI runs them.
7. **OPS-002 is done.** A staging deployment exists and has passed an end-to-end acceptance run.
8. **An independent review** has been carried out, because this one was done by the author of the
   code.

**Until then:** synthetic data only, and no prescription issued through the system has any
standing outside the practice. The MVP may be used to exercise the software; it may not be used to
treat anyone.

## 9. The remediation list

Ordered by what blocks what. The first group has to happen before any patient data exists; the
second before a staging deployment; the rest can follow the deployment.

**Group 1 — before any real patient data**

| # | Finding | Remediation | Owner |
| --- | --- | --- | --- |
| 1 | REG-01 | Name the jurisdiction; have REG-02…REG-07 answered against it | the practice |
| 2 | REG-02 | Adopt the national drug terminology and verify the mapping | engineering |
| 3 | REG-04 | Refuse anything outside the approved catalogue; refuse controlled substances | engineering + practice |
| 4 | PRIV-02 | Consent capture, with an approved notice | practice + engineering |
| 5 | PRIV-03, PRIV-04 | A written retention schedule, a purge process, a position on erasure | practice + legal |
| 6 | SEC-04 | A lockout that works across instances | engineering |
| 7 | SEC-05 | TLS, with HSTS once the domain is known | engineering |
| 8 | SEC-06 | A durable audit log whose chain head survives a restart | engineering |

**Group 2 — before a staging deployment**

| # | Finding | Remediation | Owner |
| --- | --- | --- | --- |
| 9 | PRIV-05 | Encrypted object storage for the prescription documents | engineering |
| 10 | PRIV-09 | Replace the placeholder canonical base URL | engineering |
| 11 | SEC-07 | Anchor the audit chain head outside the log | engineering |
| 12 | SEC-08, SEC-09 | Decide on SMART or a first-party-only API; a CORS allowlist | engineering + practice |
| 13 | SEC-10 | Conditional create and update | engineering |
| 14 | SEC-15, SEC-14 | A real server behind a proxy; an access log | engineering |
| 15 | A11Y-01 | A user interface, assessed against WCAG 2.1 AA | engineering + practice |

**Group 3 — after the deployment**

| # | Finding | Remediation | Owner |
| --- | --- | --- | --- |
| 16 | PRIV-06 | Project the clinical view of a patient record | engineering + practice |
| 17 | PRIV-07 | Decide between `404` and `403` for a resource that is not the caller's | engineering + practice |
| 18 | SEC-11, SEC-12, SEC-13 | Breached-password screening, MFA if required, session lifetimes | engineering + practice |
| 19 | SEC-16 | State the API's client policy | engineering |
| 20 | A11Y-02, A11Y-03, A11Y-04 | An accessible rendering of the prescription, localised errors, escaping guidance | engineering |
| 21 | REG-03, REG-05, REG-06, REG-07 | Paper or electronic prescribing, the patient's location, the not-for-emergencies statement, clinical governance | practice + legal |
| 22 | REG-08, REG-09, REG-10, REG-11 | The data-protection work of the jurisdiction, the third role, consent to telehealth | practice |

**Closed in this branch**

| # | Finding | Fix | Test |
| --- | --- | --- | --- |
| 1 | SEC-01 | A decoy verification on the unknown-account path | `tests/test_compliance_remediations.py::AccountEnumerationTest` |
| 2 | SEC-02 | A password change ends every session of the account | `::SessionInvalidationTest` |
| 3 | SEC-03 | A refusal no longer explains itself | `::ResponseHeaderTest` |
| 4 | PRIV-01 | No response is cacheable | `::ResponseHeaderTest` |

## 10. What to re-check

After the remediations, a re-review should look at: the login path end to end, with a timer and
with an attempt to enumerate; the audit log after a restart, and the chain after a rewrite; the
response headers of every route; what the API returns to a clinician who is not the patient's
clinician; and the retention behaviour of every table that grows. It should also repeat the parts
of this review that could not be done here: a penetration test, a review of the deployment, and the
regulatory answers of §7.

# Authentication, authorization and audit design

- **Feature:** `ENG-002` — implement authentication, authorization, and audit logging
- **Status:** Implemented and tested. The application layer is in-memory; the PostgreSQL schema is in
  [`db/auth_schema.sql`](../db/auth_schema.sql) and has **not** been executed (no PostgreSQL server is
  available in the development environment).
- **Owner:** `OpenCode-20261019-76cfc753`

## 1. Acceptance criteria

The backlog item is: *"both roles authenticate; access is role-scoped; record and prescription access
is audit-logged."* This is how that is met:

| Criterion | Where | Evidence |
| --- | --- | --- |
| Both roles authenticate | `telemedicine/auth.py` — one account type, two roles | `tests/test_auth.py::AuthenticationTest::test_both_roles_authenticate` |
| Access is role-scoped | `telemedicine/authorization.py` — explicit rule table plus a per-record scope | `tests/test_authorization.py` (rule table and service level) |
| Record access is audit-logged | `telemedicine/records.py` — every read writes an entry, allowed or refused | `tests/test_authorization.py::RecordsServiceAccessTest::test_every_read_of_a_record_leaves_an_audit_entry` |
| Prescription access is audit-logged | `telemedicine/records.py` — issue and read both audited | `tests/test_authorization.py::RecordsServiceAccessTest::test_prescription_creation_is_audited_against_the_encounter` |
| The audit log is tamper-evident | `telemedicine/audit.py` — hash chain, append-only | `tests/test_audit.py::TamperDetectionTest` |

## 2. Roles and trust boundaries

Two roles exist, matching the two actors in the README:

- **patient** — books appointments, joins consultations, views their own record and their own
  prescriptions.
- **practitioner** — the clinician: sees the patients they treat, records encounters, issues
  prescriptions.

A third role (practice administrator) is not modelled. The MVP is a single-clinician practice, and
adding an administrator role would add a way to read every patient's record, which is exactly the
access the privacy gate is about.

The trust boundary is the API. Everything in `telemedicine/` is application logic that the API layer
(ENG-006) must call *before* touching data — no endpoint may read a record without going through
`RecordsService`.

## 3. Passwords

| Property | Choice | Why |
| --- | --- | --- |
| Algorithm | PBKDF2-HMAC-SHA256, 600 000 iterations | Standard-library only, OWASP-recommended cost for SHA-256 |
| Salt | 16 random bytes per password | Two accounts with the same password get different hashes |
| Storage | `pbkdf2_sha256$<iterations>$<salt>$<hash>` | The cost is stored, so it can be raised later without a migration |
| Verification | `hmac.compare_digest` | Constant time |
| Policy | At least 12 characters; not the account's own email | A floor, not a ceiling — see the limitations |

The iteration count is a constructor argument on `AuthService`, so the tests can use a small value
while production uses the default. The algorithm under test is the same.

**Failed logins are audited, and the audit entry does not contain the full email address** — only a
masked form such as `a***@example.org`. A login for an unknown account produces the same error
message and the same timing profile as a wrong password, so the login form cannot be used to
enumerate accounts.

## 4. Sessions

- A session token is 32 bytes from `secrets.token_urlsafe`, shown to the client exactly once.
- Only the SHA-256 digest of the token is stored (`auth_session.token_hash`). A leaked table yields
  no usable token. The digest is not a password hash on purpose: the token is already high-entropy
  random data, so there is nothing to brute-force.
- Sessions expire after 8 hours by default and can be revoked explicitly at logout.
- A disabled account cannot log in, cannot start a session, and cannot use a session it already
  holds.
- The service re-reads the account from the repository before each decision, so a stale in-memory
  copy of a user object cannot be used to bypass a disable.

Transport requirements that the API layer must enforce: sessions must travel over TLS, must be
carried in a `Secure`, `HttpOnly`, `SameSite` cookie, and the token must never be logged.

## 5. Authorization

Decisions are made by `Authorizer.decide(actor, action, resource_type, scope)` from two inputs: a
static rule table, and an `AccessScope` assembled from the data for the specific record.

### 5.1 The rules

| Role | Resource | Action | Scope |
| --- | --- | --- | --- |
| patient | patient / appointment / encounter / medication_request | read | own |
| practitioner | practitioner | read | own |
| practitioner | patient / appointment / encounter | read | treating |
| practitioner | encounter | create | treating |
| practitioner | medication_request | read | treating or issuer |
| practitioner | medication_request | create | treating |

Anything not in this table is denied. There is no wildcard and no implicit allow, so adding a
resource type without a rule fails closed.

### 5.2 The scope

The scope is derived from the clinical data, not from a flag someone can forget to set:

- `owner_user_id` — the account that owns the record (the patient for patient data, the
  practitioner for a practitioner record);
- `treating_user_ids` — the accounts of clinicians with an appointment or an encounter with the
  patient in question;
- `issued_by_user_id` — for a prescription, the clinician who issued it.

So "may this practitioner see this patient?" is answered by "do they have an appointment or an
encounter with them?", which is the same fact the booking feature maintains. A practitioner with no
relationship to a patient has no access to that patient's record, and the denial is audited.

### 5.3 The two errors are different

`AuthenticationError` means "who are you". `AuthorizationError` means "I know who you are, and you
may not do that", and it carries the resource type, resource id and action so the audit layer can
record exactly what was refused. The API layer will map them to 401 and 403 respectively.

## 6. Audit

The README lists "tamper-evident logs for access to records and prescriptions" as a release gate,
so the log is not a plain table.

- **Append-only.** Entries are frozen dataclasses; the log exposes them as a tuple and has no update
  or delete method. The database enforces the same rule with a trigger that rejects `UPDATE`,
  `DELETE` and `TRUNCATE` on `audit_log`.
- **Tamper-evident.** Each entry stores the hash of the entry before it, and its own hash covers its
  content and that link. Changing, removing or reordering an entry breaks the chain from that point
  on. `AuditLog.verify_chain()` reports whether the chain is intact and `find_chain_break()` reports
  where it broke.
- **Refuses to extend a broken chain.** Appending to a log whose chain is already broken raises
  `AuditError` rather than hiding the corruption.
- **What is recorded:** account creation, every login attempt (allowed or refused), every password
  change, every logout, every read of a patient record, appointment, encounter or prescription, and
  every prescription issued — each with the outcome (`success`, `denied`, `error`).
- **What is not recorded:** the plaintext password, the raw session token, and the full email address
  of a failed login.

The hash payload is the entry's own fields plus the previous hash, serialised as canonical JSON.
The Python implementation and the SQL schema agree on this, so a log can be verified by either.

## 7. Persistence

| Table | Purpose | Python counterpart |
| --- | --- | --- |
| `user_account` | Accounts, password hashes, role, the link to the clinical record | `UserRepository` |
| `auth_session` | Session digests, expiry, revocation | `SessionStore` |
| `audit_log` | The append-only chain | `AuditLog` |

`account_ref` in `user_account` is the opaque link to `patient.id` or `practitioner.id` that ENG-001
added to the clinical tables. It is deliberately not a foreign key: the two features must not
constrain each other's table layout, and the clinical tables are not modified by ENG-002.

The repositories are in-memory. Replacing them with database-backed ones is the only change needed
to persist accounts; the service and authorization layers do not change.

Writing an audit entry concurrently needs care: the writer must read the chain head and insert
inside one transaction holding an advisory lock, or two writers can fork the chain. The schema
documents the lock to use.

## 8. Mapping to the README's compliance gates

| Gate (README) | Status after ENG-002 |
| --- | --- |
| Security: strong authentication | Partly met — password hashing, session lifecycle, role-scoped authorization. Not met: MFA, lockout, TLS enforcement |
| Security: role-based authorization | Met for the records in scope; the API must enforce it for every endpoint |
| Auditability: tamper-evident logs | Met for record and prescription access, and for authentication events |
| Privacy: minimum-necessary data access | Met for the read paths — the treatment relationship is the only thing that grants access |
| Privacy: consent capture, retention policy | **Not met.** No consent capture and no retention policy; both are OPS-001 |

## 9. Limitations and open items

1. **No persistence.** The repositories are in memory; a restart loses accounts and sessions.
2. **No database execution.** `db/auth_schema.sql` has not been run against PostgreSQL.
3. **No lockout or rate limiting.** `failed_attempts` and `locked_until` exist in the schema but
   nothing writes them, and a single-process in-memory counter would be wrong behind more than one
   instance. This is a real gap for a credential-stuffing defence.
4. **No password reset or email.** There is no mail transport in the MVP, so there is no reset flow.
   A deployment needs one before it can serve real patients.
5. **No multi-factor authentication.** OPS-001 must decide whether the jurisdiction requires it.
6. **No consent capture and no retention policy** for the audit log, which grows without bound. The
   archive must preserve the chain or record the hash the archive starts from.
7. **The `https://telemedicine.example.org` placeholder** in the medication code system and the
   identifier URIs still needs replacing with the deployment's canonical base URL.
8. **The session TTL is a constant**, not a per-role or per-risk value.

## 10. What ENG-006 must do

- Map `AuthenticationError` to 401 and `AuthorizationError` to 403, and never leak which of the two
  occurred in a way that reveals account existence.
- Authenticate every request before reaching `RecordsService`; there must be no code path that reads
  a clinical record without an authorization decision and an audit entry.
- Carry the session in a `Secure`, `HttpOnly`, `SameSite` cookie, and redact the token from logs.
- Decide how the FHIR layer maps roles onto FHIR scopes and capabilities, so that a FHIR client
  cannot widen its access beyond what the role allows.
- Apply the same rules to read and write paths, including the prescription download in ENG-005.

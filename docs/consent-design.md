# The consent record, and the endpoints that reach it

- **Feature:** ENG-015 — the consent service over HTTP
- **Why it exists:** section 35 of the Nigeria Data Protection Act 2023 gives a data subject the
  right to withdraw consent at any time, and says that "the data controller shall ensure that it is
  as easy for the data subject to withdraw, as to give consent". A right that can only be exercised
  by writing to the practice is not a right that is easy to exercise.
- **What the law requires, and where it comes from:** `docs/compliance/nigeria.md` §3.

## The shape of it

**The clinical record does not rest on consent.** It is made under section 30(1)(g) — medical care,
under the responsibility of a professional owing a duty of confidentiality. The patient is told about
it in the section 27 notice; they do not sign for their own treatment.

**Consent is for the optional uses**, one at a time: research, teaching, marketing, sharing with
another provider. Section 30(1)(a) requires it "for the specific purpose or purposes for which it
will be processed", and section 35 requires that each can be withdrawn on its own.

So there are two things, and the code keeps them apart:

| | What it is | Where it is recorded |
| --- | --- | --- |
| **the notice** | what the patient must be told before their data is collected | an *acknowledgement*, with the version of the notice |
| **the consents** | the optional uses, each with its own consent | one event per purpose, each grantable and withdrawable |

A consent that cannot be tied to the version of the notice the patient saw is a consent nobody can
show was informed. So every consent names its notice version, and the endpoint refuses one that
does not.

## The endpoints

| | |
| --- | --- |
| `GET /fhir/consent` | the caller's own consent state |
| `GET /fhir/consent?patient=<id>` | a patient's state, for a clinician who treats them |
| `POST /fhir/consent/notice` | record that the notice was shown |
| `POST /fhir/consent/<purpose>` | grant a consent for one optional purpose |
| `DELETE /fhir/consent/<purpose>` | withdraw it |
| `POST /fhir/consent/<purpose>/withdraw` | the same withdrawal, for the clients that would rather ask with a POST |

**A withdrawal is one request, and it does not need a clinician.** The patient takes it back on
their own, in the same number of steps as giving it, which is what section 35 asks for: "as easy
for the data subject to withdraw, as to give consent".

They are under the FHIR API because they are about the caller's own account, in the same way the
session endpoint is, and because a client already talks to one base path.

The request body of a change:

```json
{
  "notice_version": "2026-10-21",
  "method": "web",
  "evidence": "the signed form, or whatever the practice records"
}
```

`notice_version` is required. `method` and `evidence` are optional and describe how the patient
gave it — `evidence` is free text, because what a practice records differs from one practice to the
next.

The state that comes back:

```json
{
  "notice_acknowledged": true,
  "notice_version": "2026-10-21",
  "notice_acknowledged_at": "2026-10-21T12:00:00Z",
  "purposes": [
    {
      "purpose": "research",
      "description": "Using your records, with the identifying details removed, for research...",
      "state": "granted",
      "notice_version": "2026-10-21",
      "changed_at": "2026-10-21T12:00:00Z"
    }
  ]
}
```

`not_granted` is the absence of a decision, which is different from a decision not to agree. The
state says which it is, because a patient who has not been asked must not look like one who said
no.

## Who may do what

The rules are in the rule table of `telemedicine/authorization.py`, with the rest of the
application's access control, because that is where an access decision belongs.

| | Read | Change |
| --- | --- | --- |
| **the patient** | their own | their own |
| **a clinician who treats the patient** | the patient's | **nothing** |

A clinician has to know whether a patient agreed before they use a record for a research purpose —
that is the whole point of capturing the consent. What they may not do is grant or withdraw it:
consent is the patient's own act, and a clinician who could press the button on their behalf could
take it away as well. There is no rule for it, so the request is denied.

**A patient id that does not exist and a patient id the caller may not see look the same.** Both
answer `403`. Otherwise the endpoint is a way of finding out which patients the practice has.

## The record

`consent_event`, in `db/consent_schema.sql`. It is **append-only**, like the audit log: a withdrawal
is a new row, not a change to the old one, so what the patient agreed to and when they stopped
agreeing to it can both be shown. The database refuses an update, a delete and a truncate on it.

Every change is audited, and so is every refusal — a caller who was refused is exactly the thing an
audit trail exists to show. A clinician reading a patient's state is audited as well, because it is
an access to personal data.

## The gate

**Every optional use goes through one gate**, `ConsentService.require_consent(user, purpose)`. It
is asked **at the moment the use happens**, not when the consent was taken, so a withdrawal takes
effect at once: the next attempt is refused, with the reason.

That is the whole of the "block further processing" requirement, and it is one place rather than
one check in each use. The use that exists today: the recording of a consultation (ENG-019). The
uses that do not exist yet — research, teaching, sharing with another provider — will go through
the same gate.

**What the gate does not do:** it cannot stop a use that is already running. A recording that was
already going when the patient withdrew is not stopped by the withdrawal, because the media server
is doing the recording and the application is not in that loop. The next token is refused, so no
new recording starts.

## The patient's page

`web/consents.html` — one page, no build step: it signs in, lists what the patient has agreed to
and what they have withdrawn, and has a **"Withdraw consent"** button for each one. It is the
smallest honest version of a patient dashboard, which this project does not have (A11Y-01).

## What it does not do

- **There is no registration endpoint.** The notice is acknowledged by an explicit act
  (`POST /fhir/consent/notice`), not as part of signing up, because there is no HTTP sign-up yet.
- **The wording is the practice's.** The draft notice and the four drafts are in
  `docs/compliance/privacy-notice-draft.md`, marked as drafts. The version string a client sends is
  whatever the practice says it is; the software ties the consent to it and does not decide what it
  should be.
- **The consent state is not a FHIR resource.** FHIR R4 has a `Consent` resource, and mapping it
  would be the tidiest thing to do; it is not done, and the endpoint returns plain JSON in the
  meantime. A resource that claims to be a `Consent` and does not satisfy the profile would be
  worse than an endpoint that plainly is not FHIR.
- **A clinician cannot see whether a patient has read the notice**, only whether it was
  acknowledged. The acknowledgement is a record of the practice having shown it, not of the patient
  having understood it.

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

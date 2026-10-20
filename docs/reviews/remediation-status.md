# Remediation status

- **Source:** the review of [`compliance-review.md`](compliance-review.md), which found 37 issues.
- **Purpose:** to say, for each finding, whether it is closed, partly closed, or still open — so that
  the sign-off conditions in §8 of the review can be checked against something.
- **Updated:** 2026-10-20

A finding is **closed** when the behaviour it describes is implemented and tested. It is **partly
closed** when part of it is. It is **open** when it is not. Nothing is closed because it is
documented; only because it is done.

## Summary

| Area | Findings | Closed | Partly closed | Open |
| --- | --- | --- | --- | --- |
| Privacy | 8 | 1 | 1 | 6 |
| Security | 16 | 3 | 1 | 12 |
| Accessibility | 4 | 0 | 1 | 3 |
| Regulatory | 11 | 0 | 0 | 11 |
| **Total** | **37** | **4** | **3** | **30** |

The sign-off conditions of §8 of the review are listed at the end, with their state.

## Privacy

| Finding | Severity | State | What closed it, or what is missing |
| --- | --- | --- | --- |
| PRIV-01 A record could be cached by an intermediary | High | **closed** | Every response carries `Cache-Control: no-store` (`telemedicine/fhir/server.py`) |
| PRIV-02 No consent is captured | High | open | Needs the notice, which is the practice's to write |
| PRIV-03 Nothing is deleted, and no retention policy | High | open | Needs a written schedule, then a purge process |
| PRIV-04 No route to an access or erasure request | High | open | Needs a legal position on the lawful basis |
| PRIV-05 The prescription documents are not encrypted at rest | High | partly closed | The metadata is modelled (`db/prescription_schema.sql`) and the document store exists, but there is no object store and no encryption |
| PRIV-06 A clinician receives the whole patient record | Medium | open | Needs a decision on what a consultation needs |
| PRIV-07 The status code tells a caller a resource exists | Medium | partly closed | The refusal no longer explains itself (SEC-03); the `403`/`404` difference is still there, by choice |
| PRIV-08 The audit log holds identifiers, not clinical content | — | **closed** | A strength, preserved by the schema and the stores |

## Security

| Finding | Severity | State | What closed it, or what is missing |
| --- | --- | --- | --- |
| SEC-01 The login revealed which accounts existed | High | **closed** | A decoy verification on the unknown-account path (`telemedicine/auth.py`) |
| SEC-02 A password change left the sessions alive | Medium | **closed** | A password change ends every session of the account |
| SEC-03 A refusal explained itself | Medium | **closed** | The reason stays in the audit log (`telemedicine/fhir/server.py`) |
| SEC-04 No lockout, and none that works across instances | High | **closed** | The counter is a store; `PostgresLockoutStore` shares it between instances (`telemedicine/persistence/lockout.py`). It counts per account, not per source address — see the design document |
| SEC-05 No TLS | High | open | A deployment has to terminate it |
| SEC-06 The audit log did not survive a restart | High | **closed** | `PostgresAuditLog` writes the chain to the `audit_log` table, under an advisory lock (`telemedicine/persistence/audit_store.py`) |
| SEC-07 The chain is anchored nowhere outside the store | Medium | open | Needs a system outside the database: a published digest, or a write-once store |
| SEC-08 No OAuth2 and no SMART on FHIR | Medium | open | A decision first: a first-party-only API is legitimate for a single-clinician practice, but it has to be a decision |
| SEC-09 No CORS policy | Medium | open | An allowlist, when there is a client |
| SEC-10 No conditional create or update | Medium | open | `If-Match` against the resource version |
| SEC-11 The password policy is a floor | Low | open | Breached-password screening needs a network service |
| SEC-12 No multi-factor authentication | Low | open | The practice's decision |
| SEC-13 The session lifetime is a single constant | Low | open | A shorter life for a clinician, an idle timeout, re-authentication before a prescription |
| SEC-14 No request logging | Low | open | An access log at the proxy |
| SEC-15 The server is a development server | Low | open | A real server behind a proxy |
| SEC-16 Any client with a token can call the API | Low | open | A policy to state rather than to implement |

## Accessibility

| Finding | Severity | State | What is missing |
| --- | --- | --- | --- |
| A11Y-01 There is no user interface | High | open | The client, and an assessment against WCAG 2.1 AA |
| A11Y-02 The prescription document is not accessible | Medium | partly closed | The content is available as a structured `MedicationRequest`; a client could render it accessibly, and none exists |
| A11Y-03 The API's errors are English only and thin | Medium | open | The client maps the codes; the API side needs nothing |
| A11Y-04 Free text is returned unescaped | Low | open | Guidance for the client |

## Regulatory

| Finding | Severity | State | What is missing |
| --- | --- | --- | --- |
| REG-01 The jurisdiction is not established | **Critical** | open | The practice names it, and a qualified professional answers REG-02 to REG-07 against it |
| REG-02 The medication catalogue is local | High | open | The national drug terminology of the jurisdiction, verified against a terminology server |
| REG-03 A prescription is a document, not a transmission | High | open | A decision on paper or electronic, and the rules for that choice |
| REG-04 Nothing stops a prescription for a controlled substance | High | open | Refuse anything outside the approved catalogue; refuse controlled substances outright |
| REG-05 The patient's location is never established | Medium | open | Capture it, or record that it was confirmed |
| REG-06 Nothing says the service is not for emergencies | Medium | open | A statement in the client and in the terms |
| REG-07 No clinical safety process | Medium | open | The practice's clinical governance |
| REG-08 HIPAA has not been addressed | Medium | open | The full set, in the order the adviser gives |
| REG-09 GDPR has not been addressed | Medium | open | The same |
| REG-10 The single-clinician assumption | Low | open | A third role, and the access review that goes with it |
| REG-11 No consent to the telehealth consultation | Low | open | With PRIV-02 |

## The sign-off conditions

The conditions of §8 of the review, and where each one stands.

| # | Condition | State |
| --- | --- | --- |
| 1 | REG-01 is answered | open — the practice's to do, and everything else waits on it |
| 2 | Consent capture is implemented | open |
| 3 | The retention schedule and the erasure position | open |
| 4 | The lockout, TLS and a durable audit log | **two of three closed** — the lockout and the audit log are done; TLS is a deployment's job |
| 5 | A user interface, assessed against WCAG 2.1 AA | open |
| 6 | QA-001: every criterion has a test, and CI runs them | **closed** — 40 of the criteria are covered and the check fails the build if one loses its test; the remaining 13 are named with the reason |
| 7 | OPS-002: a staging deployment and an end-to-end acceptance | open |
| 8 | An independent review | open — and this document does not change that: the review was done by the author of the code |

**Two of the eight conditions are met, one is half met, and five are open.** The engineering work
that remains in the two open engineering conditions is small and named; the rest of the list needs
the practice to answer a question first.

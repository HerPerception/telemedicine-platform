# Remediation status

- **Source:** the review of [`compliance-review.md`](compliance-review.md), which found 37 issues.
- **Purpose:** to say, for each finding, whether it is closed, partly closed, or still open — so that
  the sign-off conditions in §8 of the review can be checked against something.
- **Updated:** 2026-10-20
- **Jurisdiction:** Nigeria, answered by the practice on 2026-10-20. The answers, and the law they
  rest on, are in [`docs/compliance/nigeria.md`](../compliance/nigeria.md).

A finding is **closed** when the behaviour it describes is implemented and tested. It is **partly
closed** when part of it is. It is **open** when it is not. Nothing is closed because it is
documented; only because it is done.

## Summary

| Area | Findings | Closed | Partly closed | Open |
| --- | --- | --- | --- | --- |
| Privacy | 9 | 4 | 3 | 2 |
| Security | 18 | 9 | 0 | 9 |
| Accessibility | 4 | 0 | 1 | 3 |
| Regulatory | 13 | 6 | 1 | 6 |
| **Total** | **44** | **19** | **5** | **20** |

The review found 37 issues; seven more were found while the work was being done, and are marked
*(new)* in the tables below. The counts here are of all 44.

The sign-off conditions of §8 of the review are listed at the end, with their state.

## Privacy

| Finding | Severity | State | What closed it, or what is missing |
| --- | --- | --- | --- |
| PRIV-01 A record could be cached by an intermediary | High | **closed** | Every response carries `Cache-Control: no-store` (`telemedicine/fhir/server.py`) |
| PRIV-02 No consent is captured | High | **closed** | `telemedicine/consent.py` records a consent for each optional purpose separately, withdraws them one at a time, and keeps the record of the notice apart from the consents (`db/consent_schema.sql`, append-only, like the audit log). ENG-015 put it behind an API, so a patient can grant and withdraw over HTTP — one request each, which is what section 35 of the Act asks for — and a clinician who treats them can read the state but change nothing (`docs/consent-design.md`). The draft notice and the four draft consents are in `docs/compliance/privacy-notice-draft.md`; the *wording* is the practice's document and is not marked up yet, which is an action for the practice rather than a gap in the software |
| PRIV-03 Nothing is deleted, and no retention policy | High | partly closed | The requirement is now known — section 27(1)(e) of the NDPA requires the notice to state a retention period — and the policy is in `config/retention_policy.yaml`, with the periods marked as placeholders until an adviser confirms them. ENG-017 built the job: it finds what is past its period, soft-deletes into a trash table, waits thirty days, removes it for good, and writes every removal to an immutable table with the reason. **Nothing is deleted**: the policy carries two flags, `enabled` and `legal_advisor_signed`, and both are false. Missing: the confirmed periods, and the adviser's sign-off |
| PRIV-04 No route to an access or erasure request | High | open | The lawful basis is now known — section 30(1)(g) of the NDPA: medical care, under the responsibility of a professional owing a duty of confidentiality — so the route can be built. Missing: the route itself, and the answer to what may not be deleted |
| PRIV-05 The prescription documents are not encrypted at rest | High | partly closed | The metadata is modelled (`db/prescription_schema.sql`) and the document store exists, but there is no object store and no encryption |
| PRIV-06 A clinician receives the whole patient record | Medium | open | Needs a decision on what a consultation needs |
| PRIV-07 The status code tells a caller a resource exists | Medium | partly closed | The refusal no longer explains itself (SEC-03); the `403`/`404` difference is still there, by choice |
| PRIV-08 The audit log holds identifiers, not clinical content | — | **closed** | A strength, preserved by the schema and the stores |
| *(new)* No breach report could be produced | — | **closed** | `scripts/report_breach.py` assembles the section 40(2) report from the audit log — the categories and approximate numbers of data subjects and records concerned — and says on its face which parts only the controller can decide |

## Security

| Finding | Severity | State | What closed it, or what is missing |
| --- | --- | --- | --- |
| SEC-01 The login revealed which accounts existed | High | **closed** | A decoy verification on the unknown-account path (`telemedicine/auth.py`) |
| SEC-02 A password change left the sessions alive | Medium | **closed** | A password change ends every session of the account |
| SEC-03 A refusal explained itself | Medium | **closed** | The reason stays in the audit log (`telemedicine/fhir/server.py`) |
| SEC-04 No lockout, and none that works across instances | High | **closed** | The counter is a store; `PostgresLockoutStore` shares it between instances (`telemedicine/persistence/lockout.py`). ENG-013 gave the service the address a request came from: an address is blocked after five failures, and an account is locked only when the failures are spread over twenty different addresses, so one attacker cannot lock a patient out of their own results |
| SEC-05 No TLS | High | open | A deployment has to terminate it |
| SEC-06 The audit log did not survive a restart | High | **closed** | `PostgresAuditLog` writes the chain to the `audit_log` table, under an advisory lock (`telemedicine/persistence/audit_store.py`) |
| SEC-07 The chain is anchored nowhere outside the store | Medium | **closed** | `telemedicine/audit_anchor.py`: the head of the chain is published outside the database, and `scripts/verify_audit_chain.py` checks the chain against the anchors. A chain rewritten from the beginning verifies internally and fails against the anchors |
| SEC-08 No OAuth2 and no SMART on FHIR | Medium | **closed** | The decision has been made: a first-party-only API is what this practice needs, and the SMART client is built and **switched off** (ENG-020) — the discovery document, the redirect to the record, the code exchange with PKCE and a signed state. A practice that is not connected to a hospital's record does not need it, and with the flag unset the endpoints are not registered at all. The application is not an OAuth2 *server* for other applications, and nothing in the MVP needs that |
| SEC-09 No CORS policy | Medium | open | An allowlist, when there is a client |
| SEC-10 No conditional create or update | Medium | open | `If-Match` against the resource version |
| SEC-11 The password policy is a floor | Low | open | Breached-password screening needs a network service |
| SEC-12 No multi-factor authentication | Low | open | The practice's decision |
| SEC-13 The session lifetime is a single constant | Low | open | A shorter life for a clinician, an idle timeout, re-authentication before a prescription |
| SEC-14 No request logging | Low | open | An access log at the proxy |
| SEC-15 The server is a development server | Low | open | A real server behind a proxy |
| SEC-16 Any client with a token can call the API | Low | open | A policy to state rather than to implement |
| *(new)* The accounts, the sessions and the prescription documents were held in memory, so they were neither shared between instances nor durable | — | **closed** | `telemedicine/persistence/account_store.py` and `document_store.py`: the `user_account`, `auth_session` and `prescription_document` tables. A session issued on one instance is accepted by another, which is what decides where a request may be load-balanced to |
| *(new)* The clinical records were held in memory, so nothing was durable and two instances saw different patients | — | **closed** | `telemedicine/persistence/clinical_store.py` and `telemedicine/repositories.py`: the services ask a repository for the records instead of holding them. The database's partial unique index is now the guarantee against double-booking across instances, and the store turns its refusal into the same conflict the service raises |

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
| REG-01 The jurisdiction is not established | **Critical** | **closed** | **Nigeria**, answered by the practice on 2026-10-20, and confirmed against the Nigeria Data Protection Act 2023 and the National Health Act 2014. The answers and the sources are in `docs/compliance/nigeria.md` |
| REG-02 The medication catalogue is local | High | partly closed | The answer: there is no national medication terminology in force yet, so a prescription must carry both an international code (RxNorm, with SNOMED CT or ATC alongside) for the safety checks, and the local identity (brand name and NAFDAC number) for dispensing. The statutory list is the Essential Drugs List under section 39 of the National Health Act 2014. **ENG-016 carries the local identity**: the brand, the strength and the NAFDAC registration number are on the prescription, in the database and in the FHIR resource, and a prescription without them is not printed. Missing: the coded concept is still the practice's local code system, and the Essential Drugs List is not embedded, so nothing checks that a medicine is on it |
| REG-03 A prescription is a document, not a transmission | High | open | A decision on paper or electronic, and the rules for that choice |
| REG-04 Nothing stops a prescription for a controlled substance | High | open | Refuse anything outside the approved catalogue; refuse controlled substances outright |
| REG-05 The patient's location is never established | Medium | open | Capture it, or record that it was confirmed |
| REG-06 Nothing says the service is not for emergencies | Medium | open | A statement in the client and in the terms |
| REG-07 No clinical safety process | Medium | open | The practice's clinical governance |
| REG-08 HIPAA has not been addressed | Medium | **closed** | Not applicable: the practice and its patients are in Nigeria, and the United States' regime does not reach them. The applicable regime is the NDPA 2023 and the National Health Act 2014. This closes only for as long as every patient is in Nigeria |
| REG-09 GDPR has not been addressed | Medium | **closed** | Not applicable, for the same reason as REG-08. A patient who is in the European Economic Area, or a provider whose servers are, brings the question back — which is why the media server is to be run in Nigeria (`docs/compliance/nigeria.md` §7) |
| REG-10 The single-clinician assumption | Low | open | A third role, and the access review that goes with it |
| *(new)* A media provider outside Nigeria would be an unlawful transfer | — | **closed** | Section 41 of the NDPA forbids transferring personal data out of Nigeria without an adequate basis, and section 44 requires the country of any transfer to be named in the registration. The media server is now the practice's own: LiveKit and a TURN server in `webrtc-server/`, in the country, and the application issues the access tokens. There is no third-party service involved |
| *(new)* Nothing stopped patient data being sent abroad | — | **closed** | ENG-018: every outbound path asks the gate in `telemedicine/transfer.py` before it sends anything. A service outside Nigeria needs a lawful basis and a written justification, both recorded in `config/external_services.yaml`; without them the request is refused and nothing is sent. A transfer that happens is written to `transfer_logs`, with the destination, the basis, the justification and whose data it was |
| REG-11 No consent to the telehealth consultation | Low | **closed** | The consultation is part of the care record and is made under section 30(1)(g) of the NDPA rather than by consent; the notice says so and covers the video provider, and the consent capture the notice depends on is implemented. What remains is the practice's wording, as with PRIV-02 |

## The sign-off conditions

The conditions of §8 of the review, and where each one stands.

| # | Condition | State |
| --- | --- | --- |
| 1 | REG-01 is answered | **closed** — Nigeria, answered on 2026-10-20 and confirmed against the law |
| 2 | Consent capture is implemented | **closed** — one consent per optional purpose, each withdrawable on its own, durable, audited and reachable over HTTP. The wording of the notice is the practice's, and is not marked up |
| 3 | The retention schedule and the erasure position | partly — the schedule is in the policy file, the notice's table is generated from it, and the erasure job is built and switched off in two places. The periods are placeholders and the erasure position is the adviser's |
| 4 | The lockout, TLS and a durable audit log | **two of three closed** — the lockout and the audit log are done; TLS is a deployment's job |
| 5 | A user interface, assessed against WCAG 2.1 AA | open |
| 6 | QA-001: every criterion has a test, and CI runs them | **closed** — 40 of the criteria are covered and the check fails the build if one loses its test; the remaining 13 are named with the reason |
| 7 | OPS-002: a staging deployment and an end-to-end acceptance | open — the repository side is built (`feature/ops-002-deployment`, not yet merged); the deployment itself needs a host, a certificate and a media provider |
| 8 | An independent review | open — and this document does not change that: the review was done by the author of the code |

**Three of the eight conditions are met, two are partly met, and three are open.** The engineering
work that remains in the partly met conditions is small and named; the rest of the list needs the
practice to answer a question first.

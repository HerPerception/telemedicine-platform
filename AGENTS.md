# AGENTS.md

Guidance for coding agents working in this repository.

This file was created by an agent (`OpenCode-20261019-b07bb18a`) during feature `ENG-001`. It lists
only commands that have actually been run and verified in this repository. Nothing here is a guess.

## Project

`telemedicine-platform` — a personal telemedicine MVP: appointment booking, browser video
consultations, e-prescriptions, and a FHIR R4 API. The MVP scope, acceptance criteria and
compliance gates live in [`README.md`](README.md).

## Current state

The repository contains documentation, the core data model and the security layer. There is **no
framework, no database, no CI and no deployment**. Do not assume a package manager or service
exists; check the repository before assuming anything.

| Path | Contents |
| --- | --- |
| `docs/data-model.md` | The core data model: entities, relationships, invariants, open items |
| `docs/fhir-mappings.md` | Mapping of the model onto FHIR R4 (4.0.1) resources, with the verification method |
| `docs/fhir/examples/` | One example of each modelled FHIR resource |
| `docs/auth-design.md` | Authentication, authorization and audit design, and its limitations |
| `docs/booking-design.md` | Booking, schedule management and the time-zone rules |
| `docs/prescription-design.md` | E-prescriptions: issuance, the document, the lifecycle and the gaps |
| `docs/fhir-api-design.md` | The FHIR R4 API: endpoints, errors, authorization and the gaps |
| `docs/acceptance-traceability.md` | Every acceptance criterion of the MVP, whether a test covers it, and which one |
| `docs/video-design.md` | The video consultation rooms: the waiting room, admission control, join tokens and the missing transport |
| `docs/reviews/compliance-review.md` | The OPS-001 privacy, security, accessibility and regulatory review, and the remediation list |
| `db/schema.sql` | PostgreSQL DDL for the six clinical tables (ENG-001) |
| `db/auth_schema.sql` | PostgreSQL DDL for accounts, sessions and the audit log (ENG-002) |
| `db/prescription_schema.sql` | PostgreSQL DDL for the prescription document metadata (ENG-005) |
| `telemedicine/` | The application layer: `auth`, `authorization`, `audit`, `records`, `booking`, `prescriptions`, `models`, `security`, `errors` |
| `telemedicine/fhir/` | The FHIR R4 layer: `validation`, `serialization`, `repository`, `server` |
| `telemedicine/video.py`, `telemedicine/video_api.py` | The video consultation rooms and their HTTP surface |
| `scripts/validate_fhir_examples.py` | Command-line front end for `telemedicine.fhir.validation` |
| `tests/` | `unittest` suites for the FHIR examples, the schema files, authentication, authorization, audit, slots, booking, prescriptions, the FHIR API, the compliance remediations, the acceptance criteria and the video rooms |
| `.github/workflows/ci.yml` | The continuous integration: the suite, the validator and the traceability check |
| `Dockerfile`, `docker-compose.yml` | The container, and a staging environment: the API, the delivery worker and a database |
| `multi-agent-orchestrator/` | Agent coordination bookkeeping — **not** product code. Do not edit it as part of a feature. |
| `docs/persistence-design.md` | The database: the schema, the durable audit log, the shared lockout and the dependency |
| `docs/reviews/remediation-status.md` | Whether each finding of the compliance review is closed |
| `docs/compliance/nigeria.md` | The answers for the jurisdiction: the law, the decisions, and what is still to be settled |
| `docs/consent-design.md` | The consent record and the endpoints that reach it |
| `docs/compliance/privacy-notice-draft.md` | The draft privacy notice, and the four optional-use consents |
| `docs/deployment.md` | The runbook: what a deployment is, what it needs, and how to bring it up |
| `docs/notification-design.md` | The notification outbox: the confirmations, the transport and the retry |
| `db/security_schema.sql` | PostgreSQL DDL for the shared lockout counter (ENG-007) |
| `db/notification_schema.sql` | PostgreSQL DDL for the notification outbox (ENG-011) |
| `telemedicine/persistence/` | The database, the durable audit log, the shared lockout, the accounts, the sessions, the prescription documents, the clinical records and the notification outbox |
| `telemedicine/notifications.py` | The notification outbox: what the practice tells people, and when |
| `telemedicine/audit_anchor.py` | Publishing the head of the audit chain outside the database |
| `telemedicine/session_api.py` | Signing in and out over HTTP, and the address the request came from |
| `telemedicine/delivery.py` | The delivery worker, and the transport that talks to a mail server |
| `telemedicine/consent.py` | The consent record: what a patient agreed to, and what they withdrew |
| `telemedicine/consent_api.py` | The consent endpoints: a patient grants and withdraws, a clinician reads |
| `db/consent_schema.sql` | PostgreSQL DDL for the consent record — append-only, like the audit log |
| `telemedicine/repositories.py` | Where the records live, and the implementation that keeps them in memory |
| `telemedicine/config.py`, `telemedicine/application.py` | The settings, and the application assembled from them |
| `scripts/apply_schema.py` | Applies the database schema, and says what it skipped |
| `scripts/run_server.py` | Runs the application: the FHIR API and the video rooms |
| `scripts/verify_audit_chain.py` | Checks the audit chain, internally and against the anchors |
| `scripts/run_delivery.py` | Sends the queued notifications |
| `scripts/healthcheck.py` | Whether the application is ready to serve |
| `scripts/report_breach.py` | Assembles the section 40(2) breach report from the audit log |

## The jurisdiction

The practice is in **Nigeria**, and the applicable law is the **Nigeria Data Protection Act 2023**
and the **National Health Act 2014**. Two consequences that are easy to get wrong:

- the **clinical record does not rest on consent**. It is made under section 30(1)(g) — medical care,
  under the responsibility of a professional owing a duty of confidentiality. Consent is for the
  optional uses only, one purpose at a time, and each can be withdrawn on its own (section 35);
- **personal data may not be transferred out of Nigeria** without an adequate basis (sections 41–43),
  which is why the video media server is to be run by the practice, in Nigeria.

`docs/compliance/nigeria.md` is the full answer, with the sources it rests on.

## Installing

The application code uses only the Python 3 standard library, and the project has **one**
dependency: the PostgreSQL driver. It is only needed to run against a database; the tests that do
not need one run without it.

```bash
pip install -e .            # or: pip install 'psycopg[binary]'
```

A deployment needs the driver, and the application says so if it is missing.

## Verified commands

Run from the repository root. The suite runs without anything installed — the persistence tests are
skipped when there is no database — and with the driver and a server, every test runs.

```bash
# Validate the example FHIR resources against the declared mapping
python3 scripts/validate_fhir_examples.py

# Run the whole test suite
python3 -m unittest discover -s tests -v

# Run one module
python3 -m unittest tests.test_fhir_api -v
```

Expected result of the test command: `OK` (541 tests, 57 of them skipped without a database).

The persistence tests need a PostgreSQL server, and are skipped without one:

```bash
TELEMEDICINE_TEST_DSN="postgresql://postgres@localhost/postgres" \
    python3 -m unittest discover -s tests -v
```

The schema is applied with:

```bash
python3 scripts/apply_schema.py "postgresql://user@host/database"
```

The application is run with:

```bash
TELEMEDICINE_DATABASE_URL="postgresql://user@host/database" python3 scripts/run_server.py
```

Without `TELEMEDICINE_DATABASE_URL` the records stay in the memory of the
process, and the server says so.

One test reads a generated PDF with poppler's `pdftotext` and is skipped when that tool is not
installed.

The same commands run in CI (`.github/workflows/ci.yml`) on every push to `main` and on every pull
request, together with the traceability check that fails the build if an acceptance criterion loses
its test. If you add a test, run the suite locally first: it is the same command.

An acceptance criterion is covered only if `docs/acceptance-traceability.md` names the test that
covers it, and the name must be a real test. A criterion that cannot be covered yet says why.

The video rooms hold health data in transit: the join token is signed per room, the room is bound
to one appointment, and a join outside the appointment window is refused with a reason and a retry
path rather than a guess.

## Conventions

- Python 3.12. The application code is standard library only; the one dependency is
  `psycopg[binary]`, the PostgreSQL driver, which the persistence layer needs and no standard
  library can provide. It is declared in `pyproject.toml`.
- Tests use `unittest` (not pytest) because no third-party dependency is installed.
- SQL targets PostgreSQL 13+; see the header of each file in `db/`. The files are re-runnable:
  tables and indexes are created if they are not there, and triggers are dropped and created
  again. A statement that needs an extension the server does not have is marked with
  `-- @requires-extension` and skipped, and the apply says so.
- FHIR content targets **R4 (4.0.1)**. Verify element names, cardinalities and value sets against
  the published StructureDefinitions at `https://hl7.org/fhir/R4/<resource>.profile.json` rather
  than from memory.
- Identifiers in the examples and the database are bare UUIDs.
- Credentials and tokens are never logged, and the audit log records masked identifiers only.
- Authorization is fail-closed: a request that matches no rule in `telemedicine/authorization.py` is
  denied, and every access to a record goes through `telemedicine/records.py` so that it is audited.
- Times are stored as UTC instants. A local wall-clock time only becomes an instant through
  `telemedicine.booking.resolve_local_time`, which refuses daylight-saving gaps and overlaps.
- Booking changes to a schedule are recorded in the audit log under `slot.*` and `appointment.*`.
- The FHIR API is served under `/fhir` and answers with `application/fhir+json`. Every resource it
  sends is checked against the R4 profile in `telemedicine/fhir/validation.py` before it goes out,
  and a resource that fails the check is never sent.
- The API never reads or writes a record except through the domain services, so that every access is
  authorized and audited in one place.
- The services hold no records: they ask a repository, and the repository is either the memory of
  one process or the database. A deployment passes the database one.
- A message that is owed is queued in the database before it is sent, and something that is not an
  account has no actor id in the audit log.
- The head of the audit chain is published outside the database when
  `TELEMEDICINE_AUDIT_ANCHOR` is set, so that a chain rewritten from the beginning can be told
  apart from an untouched one.
- A caller signs in with `POST /fhir/session` (or `/video/session`) and signs out with `DELETE` on
  the same path. The lockout counts the address the request came from as well as the account.
- The notifications are queued in the database and sent by `scripts/run_delivery.py`, which talks to a
  mail server with the standard library's `smtplib`. Delivery is at least once.
- A deployment is described in `docs/deployment.md`, and the container and the compose file are in
  the repository. The schema is applied as a deployment step, never by the application when it
  starts.
- `docs/reviews/compliance-review.md` holds the open findings and the conditions for using real
  patient data. Nothing in this repository may handle a real patient until those conditions are met.

## Not yet established

There is no install, run, lint or CI command yet, because there is no application to run. Add the
real commands to this file once they exist and have been verified — do not add a command that has
not been executed.

## Coordination

Work is coordinated through `multi-agent-orchestrator/` in the primary checkout
(`/home/student/telemedicine-platform`): `agentmeeting.md` for claims and standups, `resolution.md`
for completed work, `coordination.md` for owner decisions and permissions. Read
`multi-agent-orchestrator/agent_activation_prompt.md` before taking ownership of a task. One
feature gets one branch and one isolated worktree.

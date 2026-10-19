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
| `db/schema.sql` | PostgreSQL DDL for the six clinical tables (ENG-001) |
| `db/auth_schema.sql` | PostgreSQL DDL for accounts, sessions and the audit log (ENG-002) |
| `telemedicine/` | The application layer: `auth`, `authorization`, `audit`, `records`, `models`, `security`, `errors` |
| `scripts/validate_fhir_examples.py` | Dependency-free validator for the example resources |
| `tests/` | `unittest` suites for the FHIR examples, the schema files, authentication, authorization and audit |
| `multi-agent-orchestrator/` | Agent coordination bookkeeping — **not** product code. Do not edit it as part of a feature. |

## Verified commands

Run from the repository root. Everything uses only the Python 3 standard library; there is nothing to
install.

```bash
# Validate the example FHIR resources against the declared mapping
python3 scripts/validate_fhir_examples.py

# Run the whole test suite
python3 -m unittest discover -s tests -v

# Run one module
python3 -m unittest tests.test_auth -v
```

Expected result of the test command: `OK` (129 tests as of the ENG-002 commit).

## Conventions

- Python 3.12, standard library only, until a dependency manifest is added.
- Tests use `unittest` (not pytest) because no third-party dependency is installed.
- SQL targets PostgreSQL 13+; see the header of each file in `db/`.
- FHIR content targets **R4 (4.0.1)**. Verify element names, cardinalities and value sets against
  the published StructureDefinitions at `https://hl7.org/fhir/R4/<resource>.profile.json` rather
  than from memory.
- Identifiers in the examples and the database are bare UUIDs.
- Credentials and tokens are never logged, and the audit log records masked identifiers only.
- Authorization is fail-closed: a request that matches no rule in `telemedicine/authorization.py` is
  denied, and every access to a record goes through `telemedicine/records.py` so that it is audited.

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

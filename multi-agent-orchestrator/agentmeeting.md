# Agent Meeting Log

- **Project:** telemedicine-platform
- **Primary checkout:** `/home/student/telemedicine-platform`
- **Coordination location:** `multi-agent-orchestrator/` (authoritative, per `agent_activation_prompt.md`)
- **Coordination mode:** **B — bootstrap.** No `scripts/agent_coordination.py` is installed. The exclusive directory `/home/student/telemedicine-platform/.agent-bootstrap-lock` is authoritative ownership while held.
- **Last updated:** 2026-10-22

> **Rebuilt on 2026-10-22** after the primary checkout was re-cloned, which took the
> untracked coordination files with it. The backlog below was rebuilt from the git history; the
> full standup log was lost with the files and is not recoverable.

## Active Agents

| Agent/session ID | Role | Status | Heartbeat UTC | Feature | Branch/worktree | Claim reference |
| --- | --- | --- | --- | --- | --- | --- |
| OpenCode-20261020-3dafd2c8 | Compliance (Nigeria) | Done-waiting (committed locally; push/PR blocked) | 2026-10-22 | ENG-023 — say what is left, and whose job it is | `feature/eng-023-what-remains` @ `/home/student/telemedicine-platform-worktrees/eng-023` (base `e6a79ff`, commit `630a268`) | `.agent-bootstrap-lock` (held and released with the work) |

## Feature Backlog

Every feature that has been implemented, with the commit that carries it. The acceptance criteria
for each are in `docs/acceptance-traceability.md`, and what is still open is in
`docs/reviews/remediation-status.md` — under *What is left, and whose job it is*.

| Feature | What it did | State |
| --- | --- | --- |
| ENG-001 | define the data model and FHIR R4 resource mappings | **merged** |
| ENG-002 | authentication, role-scoped authorization and an audit log | **merged** |
| ENG-003 | appointment booking, schedule management and time-zone rules | **merged** |
| ENG-005 | e-prescription issuance, the document, download and the lifecycle | **merged** |
| ENG-006 | expose the FHIR R4 API | **merged** |
| OPS-001 | privacy, security, accessibility and regulatory review | **merged** |
| QA-001 | a test for every acceptance criterion, and CI that runs the suite | **merged** |
| ENG-004 | video consultation rooms, the waiting room and admission control | **merged** |
| ENG-007 | the schema applied for the first time, a durable audit log, a shared lockout | **merged** |
| ENG-008 | the accounts, the sessions and the prescription documents in the database | **merged** |
| ENG-009 | the clinical records in the database, and the services stop holding them | **merged** |
| ENG-010 | the application assembled, and the whole stack over HTTP | **merged** |
| ENG-010 | the application refuses to start when it is not ready | **merged** |
| ENG-011 | the notification outbox, so a booking reaches both parties | **merged** |
| ENG-012 | anchor the audit chain outside the database | **merged** |
| ENG-013 | sign in over HTTP, and a lockout that counts the address | **merged** |
| ENG-014 | the delivery worker and the mail transport | **merged** |
| OPS-002 | the container, the settings and the runbook | **merged** |
| OPS-003 | the Nigerian answer — consent capture, the breach report, the law | **merged** |
| ENG-015 | the consent service over HTTP — a patient can withdraw | **merged** |
| ENG-016 | the prescription names the medicine the way a pharmacy dispenses it | **merged** |
| ENG-017 | the retention policy, built and switched off | **merged** |
| ENG-018 | the gate on transfers out of Nigeria | **merged** |
| ENG-019 | the media server, in Nigeria, and the token that opens a consultation | **merged** |
| ENG-020 | SMART on FHIR, built and switched off | **merged** |
| ENG-021 | the withdrawal takes effect at once, and the patient has a button | **merged** |
| ENG-022 | the demo mode, and the list of what is waiting for a lawyer | **merged** |

## Standup Entries

### 2026-10-22 — OpenCode-20261020-3dafd2c8

- **Completed:** ENG-023 — wrote down *what is left, and whose job it is*: ten findings are code, four are the deployment's, eight are a decision, three are the practice's — and two things that are not findings at all (the container has never been built, and no restore has ever been tried). A test now holds that list to the tables.
- **Also:** the primary checkout was re-cloned, which took the untracked coordination files with it. They were rebuilt from the git history: the work log, the pull request bodies, this backlog, and the owner decisions. The work itself was never at risk — it is in `main` and in the merged pull requests.
- **Blockers:** the network to github.com was unreachable for part of this session, so nothing could be pushed and the exact pull request bodies could not be fetched back from GitHub.
- **Heartbeat:** 2026-10-22.

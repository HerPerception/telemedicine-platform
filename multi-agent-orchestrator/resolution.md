# Resolution Log

Append-only. Timestamps are UTC. Corrections are appended, never rewritten.

> **Rebuilt on 2026-10-22.** The primary checkout was re-cloned, and with it this file and
> the other coordination files, which were never committed — they were bookkeeping that lived
> only in the working tree. The **work** was not lost: every feature is in the git history and
> in the merged pull requests. This log was rebuilt from that history, one entry per feature,
> and the pull request bodies in `pr-bodies/` were rebuilt from the commits.

## 2026-10-19 — ENG-001 — define the data model and FHIR R4 resource mappings

- **Commit:** `f3b3d25bd414e27313fa06f9a43bdb776cd21508` on the feature branch, merged into `main`.
- **What it did:** Adds the core data model for the telemedicine MVP and its mapping onto

## 2026-10-19 — ENG-002 — authentication, role-scoped authorization and an audit log

- **Commit:** `1dc0d584bef38b410bd2fbfb8f3eb61062da5047` on the feature branch, merged into `main`.
- **What it did:** Adds the security layer the MVP needs before any patient data exists.

## 2026-10-20 — ENG-003 — appointment booking, schedule management and time-zone rules

- **Commit:** `768878e646708beffb7fca1a4c124a87c72f992a` on the feature branch, merged into `main`.
- **What it did:** Implements the booking half of the MVP: a practitioner opens slots in their

## 2026-10-20 — ENG-005 — e-prescription issuance, the document, download and the lifecycle

- **Commit:** `22de1754fd882a54c737c06d99e3f863e7a0d15e` on the feature branch, merged into `main`.
- **What it did:** A patient must be able to download and print a prescription, and the

## 2026-10-20 — ENG-006 — expose the FHIR R4 API

- **Commit:** `52bd5520c453042bd73f60cd721fcaa4d69f2bba` on the feature branch, merged into `main`.
- **What it did:** The five core resources are now readable and writable over HTTP, with the

## 2026-10-20 — OPS-001 — privacy, security, accessibility and regulatory review

- **Commit:** `b4bb1b44f5df4050ed0c44c4e662fd9d0fcb3433` on the feature branch, merged into `main`.
- **What it did:** The MVP handles health data, and the README makes six compliance gates

## 2026-10-20 — QA-001 — a test for every acceptance criterion, and CI that runs the suite

- **Commit:** `4ae54fac979772f1c26e6d64a0190a0d64d652fb` on the feature branch, merged into `main`.
- **What it did:** The acceptance criteria of the MVP were written down in the README and in

## 2026-10-20 — ENG-004 — video consultation rooms, the waiting room and admission control

- **Commit:** `bb20429bee1cbb0cee073bea376dd5d6ca101072` on the feature branch, merged into `main`.
- **What it did:** The visit loop had no consultation in it. This adds the room a booked

## 2026-10-20 — ENG-007 — the schema applied for the first time, a durable audit log, a shared lockout

- **Commit:** `027a3b03726c7099c6562cf8c983b22abf785db4` on the feature branch, merged into `main`.
- **What it did:** Every pull request in this project carried the same caveat: the DDL had

## 2026-10-20 — ENG-008 — the accounts, the sessions and the prescription documents in the database

- **Commit:** `15865ace0c0d037a0ada30212cd5b0dcf3b2b296` on the feature branch, merged into `main`.
- **What it did:** Three more pieces of state have the same property the lockout had: they

## 2026-10-20 — ENG-009 — the clinical records in the database, and the services stop holding them

- **Commit:** `21bfa5de89d04410e2b1c03b10974a76aefb9470` on the feature branch, merged into `main`.
- **What it did:** The last records still held in dictionaries were the clinical ones, and

## 2026-10-20 — ENG-010 — the application assembled, and the whole stack over HTTP

- **Commit:** `9f7f6bf062d7ef779fb33222d177bdef075c4199` on the feature branch, merged into `main`.
- **What it did:** The application was assembled by hand: the records service, the slots, the

## 2026-10-20 — ENG-010 — the application refuses to start when it is not ready

- **Commit:** `c40b68a79b3259408eebcdd07a88e0aa8254c4d3` on the feature branch, merged into `main`.
- **What it did:** Running the application by hand showed two things that should not have

## 2026-10-20 — ENG-011 — the notification outbox, so a booking reaches both parties

- **Commit:** `48114aa8dbc5ebb436cf3391c2c2a93161efdcf4` on the feature branch, merged into `main`.
- **What it did:** The README's acceptance criteria for booking include that both parties

## 2026-10-20 — ENG-012 — anchor the audit chain outside the database

- **Commit:** `7862f4be27f3d656619aa76df021b99775c037ec` on the feature branch, merged into `main`.
- **What it did:** The chain of the audit log is only as good as the store it is in. An

## 2026-10-20 — ENG-013 — sign in over HTTP, and a lockout that counts the address

- **Commit:** `e20668d4e02969c38283724b07a4aeb6e54cddf2` on the feature branch, merged into `main`.
- **What it did:** There was no way to sign in over HTTP. The authentication service existed

## 2026-10-20 — ENG-014 — the delivery worker and the mail transport

- **Commit:** `27bae8029f918022872bb57e95ce3c5df935264e` on the feature branch, merged into `main`.
- **What it did:** The outbox of ENG-011 queued the messages and left the sending to

## 2026-10-20 — OPS-002 — the container, the settings and the runbook

- **Commit:** `675cf9ce63e583f8733d44f2a05555c8738c3549` on the feature branch, merged into `main`.
- **What it did:** The parts of a deployment that live in the repository, so that the

## 2026-10-20 — OPS-003 — the Nigerian answer — consent capture, the breach report, the law

- **Commit:** `dfccd8cf6c9dc8a9b7f6fc8df39277acc546b802` on the feature branch, merged into `main`.
- **What it did:** The practice answered the four questions the compliance review was waiting

## 2026-10-20 — ENG-015 — the consent service over HTTP — a patient can withdraw

- **Commit:** `c488cc8680ee5f9385fdcb4a76e51605dc2bf331` on the feature branch, merged into `main`.
- **What it did:** Section 35 of the Nigeria Data Protection Act 2023 gives a data subject the

## 2026-10-21 — ENG-016 — the prescription names the medicine the way a pharmacy dispenses it

- **Commit:** `02f1dd1448b33f5288748519a5b4fb06a5d6760e` on the feature branch, merged into `main`.
- **What it did:** A prescription in Nigeria is dispensed by the brand and the NAFDAC

## 2026-10-21 — ENG-017 — the retention policy, built and switched off

- **Commit:** `9366c8c9883cc392cbf0d2a7d21ff7a5464137f0` on the feature branch, merged into `main`.
- **What it did:** The practice has no legal adviser yet, and cannot decide retention

## 2026-10-21 — ENG-018 — the gate on transfers out of Nigeria

- **Commit:** `39adecf91ba45df45a56d8615a6761dd56d228c0` on the feature branch, merged into `main`.
- **What it did:** Section 41(1) of the Nigeria Data Protection Act 2023 forbids transferring

## 2026-10-21 — ENG-019 — the media server, in Nigeria, and the token that opens a consultation

- **Commit:** `fba17002d78d18978b2ea99699e438f9cae6e676` on the feature branch, merged into `main`.
- **What it did:** The consultations are carried by a server the practice runs itself, in

## 2026-10-21 — ENG-020 — SMART on FHIR, built and switched off

- **Commit:** `4194f27143e24d612304cea53314386b2e729900` on the feature branch, merged into `main`.
- **What it did:** SMART on FHIR is how a hospital's electronic health record launches an

## 2026-10-21 — ENG-021 — the withdrawal takes effect at once, and the patient has a button

- **Commit:** `c46fe1b60422fb9d543ad613461cbcb2f3055a03` on the feature branch, merged into `main`.
- **What it did:** The question this answers was whether a patient can take a consent back on

## 2026-10-21 — ENG-022 — the demo mode, and the list of what is waiting for a lawyer

- **Commit:** `af4b9808f53f7fa1954bee9c5f733e2b86ca74e0` on the feature branch, merged into `main`.
- **What it did:** The practice has no legal adviser yet. That is not a reason to leave the

## 2026-10-22 — The coordination files were rebuilt

- **What happened:** the primary checkout (`/home/student/telemedicine-platform`) was
  re-cloned. The coordination files were never committed, so they went with it: the
  backlog, the standups, the owner decisions, this work log and the pull request
  bodies. The local feature branches and the worktree registrations went too.
- **What was lost:** the coordination record itself, and DOC-001's uncommitted honest MVP
  README, which held the roadmap. The *work* was not lost: `main` holds all the merged
  features, and the pull requests are on GitHub with the bodies they were opened with.
- **What was done:** this log, the pull request bodies and the other coordination files were
  rebuilt from the git history. The exact pull request bodies can be restored from GitHub
  when the network is reachable again.

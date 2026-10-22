# Coordination

Append-only for owner decisions and agent records. Preserve other agents' entries; append corrections rather than rewriting history.

> **Rebuilt on 2026-10-22** after the primary checkout was re-cloned took this file with it. The
> decisions below are the ones that still shape the work; the record of how each was made is in the
> pull requests and in `docs/compliance/nigeria.md`.

## Project context

- **Target repository:** `telemedicine-platform` — `https://github.com/HerPerception/telemedicine-platform`
- **Primary checkout:** `/home/student/telemedicine-platform`
- **Default branch:** `main`
- **Coordination location:** `multi-agent-orchestrator/` under the primary checkout
- **Coordination mode:** **B — bootstrap.** No `scripts/agent_coordination.py` is installed. The
  exclusive directory `/home/student/telemedicine-platform/.agent-bootstrap-lock` is authoritative
  ownership while held.
- **Merge and deployment authority:** the repository owner. No delegation is recorded, and none is
  assumed.
- **The state of the work:** every feature in the backlog below is merged into `main`. What is still
  open — and whose job each part of it is — is in
  [`docs/reviews/remediation-status.md`](../docs/reviews/remediation-status.md), under *What is left,
  and whose job it is*.
- **The law:** the practice is in Nigeria, and the applicable law is the Nigeria Data Protection Act
  2023 and the National Health Act 2014. The full answer, with the sources, is in
  [`docs/compliance/nigeria.md`](../docs/compliance/nigeria.md).

## Standing Permissions

| Agent | Exact action/scope | Status | Granting authority | Timestamp (UTC) |
| --- | --- | --- | --- | --- |
| All agents | Implement a feature on its own branch and in its own worktree, and log the work | Allow | HerPerception (user, this session) | 2026-10-19T21:30:39Z |
| All agents | Commit that branch | Allow | HerPerception (user, this session) | 2026-10-19T21:30:39Z |
| All agents | Prepare a pull request body in `multi-agent-orchestrator/pr-bodies/` and give the owner the command | Allow | HerPerception (user, this session) | 2026-10-20T12:09:02Z |
| All agents | Merge any pull request, or deploy | **Not granted** | — | — |

## Owner Decisions

- **2026-10-19T21:30:39Z** — Target project confirmed as `telemedicine-platform`. README framing:
  the user selected "Honest MVP README": the README may state the MVP scope but must not claim
  delivered or live features without evidence.
- **2026-10-19T21:30:39Z** — Coordination bookkeeping was requested, because a second agent would
  join the project. That is this directory.
- **2026-10-20T12:09:02Z** — ENG-006 and ENG-005 authorised, including the recorded amendments to
  `telemedicine/authorization.py`, `telemedicine/records.py` and the corresponding tests.
- **2026-10-20T15:45:00Z** — The deployment pieces that could be built without a target environment
  were authorised ("Yes, do so").
- **2026-10-20T18:35Z** — The four questions the compliance review was waiting on were authorised,
  with the instruction: **"ask the questions in a way I can understand so I can answer them."**
- **2026-10-21T09:00:00Z** — **The jurisdiction is Nigeria**, and the patients are in Nigeria.
  Everything downstream follows from it: the NDPA 2023 and the National Health Act 2014, the
  medicine codes, the consent shape, the retention periods, the video provider and the transfers.
- **2026-10-21T09:00:00Z** — The medicine codes: the practice asked to be advised, and the advice
  was given — an international code for the safety checks **and** the brand and the NAFDAC number for
  dispensing.
- **2026-10-21T09:00:00Z** — The consent: the practice asked for "one form covering everything",
  and was told — and shown why — that the clinical record does not rest on consent at all
  (section 30(1)(g)), so the form is the section 27 notice plus one consent per optional use. The
  wording itself is the practice's and its adviser's.
- **2026-10-21T09:00:00Z** — The retention periods: the practice cannot decide them yet and has
  no adviser, so the numbers are placeholders, the mechanism is built and switched off in two
  places, and nothing is deleted.
- **2026-10-21T09:00:00Z** — The video provider: the practice asked for advice on the privacy
  trade-off, and the advice was that the media server is the practice's own, in Nigeria — a managed
  service abroad is a transfer of the patient's picture and voice.
- **2026-10-21T10:00:00Z** — The cross-border transfers: the gate was authorised, with the
  instruction that patient data must not silently go abroad. Every service outside Nigeria ships
  blocked.
- **2026-10-21T11:00:00Z** — SMART on FHIR: authorised as **optional and switched off**. It is
  only needed to connect to a hospital's record, and the practice has no such connection yet.
- **2026-10-21T13:00:00Z** — The consent withdrawal: authorised, and the acceptance was that a
  patient takes it back on their own and the use is blocked afterwards.
- **2026-10-21T14:00:00Z** — The demo mode and the legal to-do list: authorised, with the
  instruction that the documents be watermarked **"DEMO - NOT FOR REAL PATIENTS"** and the default
  be `DEMO_MODE=true`, and the recommendation to host everything in Nigeria and use test data until
  a lawyer has reviewed.
- **2026-10-22** — The work is merged by the owner, one pull request at a time, in the order the
  branches were built. Twenty-six features are merged.

## Blockers

- **No GitHub write credentials in the agent environment.** `git push` fails with `could not read
  Username`, and `gh` is not installed. The owner pushes and merges. Every branch in this project
  has been prepared locally with the command given in the pull request body.
- **The network to github.com was unreachable for part of 2026-10-22**, which also meant the exact
  pull request bodies could not be fetched back from GitHub. The rebuilt bodies in `pr-bodies/` come
  from the commits.
- **No Docker in the development environment.** The `Dockerfile` and the compose file have never
  been built or run. The first build on a machine with Docker is where they are really tested.
- **No legal adviser.** The retention numbers, the transfer bases and the wording of the notice are
  waiting for one; see `TODO_LEGAL.md`.
- **No host, no certificate, no public address.** The deployment cannot happen without them, and
  they have to be in Nigeria.
- **No hospital connection.** SMART on FHIR waits for one, and stays off without it.
- **The review was written by the author of the code.** The sign-off condition for an independent
  review is unmet, and nothing in this repository changes that.

## Agent proposals (not accepted decisions)

- **Proposed:** commit the coordination files, so that a re-clone cannot take them again. They have
  been rebuilt three times now for this reason.
- **Proposed:** restore the exact pull request bodies from GitHub when the network is reachable, in
  place of the ones rebuilt from the commits.
- **Proposed:** a restore procedure that has actually been performed. The runbook has a backup
  command; a restore that has never been run is not a restore.

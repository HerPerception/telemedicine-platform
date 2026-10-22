# Agent activation prompt

This is the protocol for working in this repository. Read it before taking ownership of a task.

## The shape of the work

**One feature gets one branch and one isolated worktree.** The primary checkout
(`/home/student/telemedicine-platform`) is for the owner; an agent works in its own worktree under
`/home/student/telemedicine-platform-worktrees/`, on its own branch, based on the tip of the last
unmerged feature.

```bash
git worktree add -b feature/<id>-<name> /home/student/telemedicine-platform-worktrees/<id> <base>
```

**Never work in the primary checkout, and never on `main`.**

## The claim

There is no claim tool installed, so the bootstrap lock is authoritative: the directory
`/home/student/telemedicine-platform/.agent-bootstrap-lock` is taken atomically (`mkdir` — it fails if
it exists) and holds `owner.md` with the identity, the session, the moment it was taken and the
purpose.

**Take the lock before the first write**, and release it when the work is committed. A lock that is
held while nothing is happening stops the next agent; a lock that is never held lets two agents
write to the same place.

## The record

Three files, in `multi-agent-orchestrator/` in the primary checkout. They are **append-only**:
a correction is appended, never a rewrite, and a mistake in the log is corrected in the log.

| File | What goes in it |
| --- | --- |
| `agentmeeting.md` | who is working on what, the backlog, and the standups |
| `resolution.md` | what was done, one entry per feature, with the commit |
| `coordination.md` | the permissions, the owner's decisions, and the blockers |

**The work is logged as it happens**, not at the end. A feature that is not in the log did not
happen, as far as the next agent is concerned.

## The pull request

The agent prepares the body in `multi-agent-orchestrator/pr-bodies/<feature>-pr-body.md` and gives
the owner the command:

```bash
git -C <worktree> push -u origin <branch>
```

**The agent does not merge, and does not deploy.** Merge authority is the owner's, and it has never
been delegated. A pull request that nobody has opened is not a pull request.

## What a feature is done when

- it is committed on its own branch, and the branch is based on the tip of the last unmerged feature;
- the suite passes: `python3 -m unittest discover -s tests -v`, and
  `python3 scripts/validate_fhir_examples.py` where the change touches the FHIR mapping;
- the acceptance criteria in `docs/acceptance-traceability.md` name the tests that cover them — a
  criterion with no test is not covered, and the check fails the build if a criterion loses its
  test;
- the documents that describe it are updated in the same branch, and the claim is released.

## Honest reporting

- **Say what was not done, and why.** A feature that is half-built and described as finished is
  worse than one that is half-built and described as half-built.
- **Do not assert what was not verified.** A test that was not run is not a test that passes; a
  container that was not built is not a container that works.
- **Correct the record in the log**, in an appended entry, when something earlier turns out to be
  wrong — including your own earlier work.

## The law

The practice is in **Nigeria**. The Nigeria Data Protection Act 2023 and the National Health Act
2014 apply; `docs/compliance/nigeria.md` is the answer, with its sources. Three things are easy to
get wrong and are recorded in that document and in `AGENTS.md`:

- the clinical record does **not** rest on consent (section 30(1)(g));
- personal data may not be transferred out of Nigeria without a recorded basis (sections 41–43);
- nothing is deleted while the retention policy says it may not be.

**No real patient data goes into this repository** until the sign-off conditions in
`docs/reviews/compliance-review.md` are met, and `TODO_LEGAL.md` is the list of what is waiting for a
lawyer.

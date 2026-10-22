# ENG-021: the withdrawal takes effect at once, and the patient has a button

The question this answers was whether a patient can take a consent back on
their own, and whether the taking back stops the use. Two of the four things
the task asked for were already there; two were not, and they are now.

**The gate.** Every optional use goes through one place,
ConsentService.require_consent(), and it is asked **at the moment the use
happens** -- not when the consent was taken. So a withdrawal is not
something that has to be noticed by somebody: it is something the next
attempt meets, and the attempt is refused with the reason. Before this, the
only check was in the recording path, and a use that did not exist yet
would have had to remember to write its own.

What the gate cannot do is stop a use that is already running: a recording
that was going when the patient withdrew is not stopped, because the media
server is doing the recording and the application is not in that loop. The
next token is refused, so no new recording starts. That is said plainly in
docs/consent-design.md rather than left to be discovered.

**The patient's page.** web/consents.html: one page, no build step. It
signs in, lists what the patient has agreed to and what they have
withdrawn, and has a "Withdraw consent" button for each one. It is the
smallest honest version of a patient dashboard, which this project does not
have.

**A second way to ask for the withdrawal.** POST
/fhir/consent/<purpose>/withdraw, for the clients that would rather not
write a DELETE. The same thing, the same audit entry, and the same
one-request effort that section 35 asks for.

**The state.** The record is append-only, so the withdrawal is a second
event and not a change to the first: what the patient agreed, and when they
took it back, are both still there. The state the patient sees says
"withdrawn".

**The audit.** The withdrawal is audited, and so is a refusal to withdraw
somebody else's.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

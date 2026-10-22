# ENG-015: the consent service over HTTP — a patient can withdraw

Section 35 of the Nigeria Data Protection Act 2023 gives a data subject the
right to withdraw consent at any time, and says the controller must make it
"as easy for the data subject to withdraw, as to give consent". The consent
service of OPS-003 could be used from inside the process and from nowhere
else: there was no way for a patient to reach it, so the right existed on
paper only. This is the endpoint that makes it real.

  GET    /fhir/consent                    the caller's own consent state
  GET    /fhir/consent?patient=<id>       a patient's state, for a clinician
                                           who treats them
  POST   /fhir/consent/notice             record that the notice was shown
  POST   /fhir/consent/<purpose>          grant a consent for one purpose
  DELETE /fhir/consent/<purpose>          withdraw it

The rules live in the rule table with the rest of the application's access
control, because that is where an access decision belongs: a patient reads
and changes their own consents, a clinician who treats the patient reads
the state — they have to know before they use a record for a research
purpose — and changes nothing. There is no rule for a clinician to change
one, so the request is denied: consent is the patient's own act, and a
clinician who could press the button on their behalf could take it away as
well.

A consent has to name the version of the notice the patient saw. A consent
that cannot be tied to the words that were read is a consent nobody can
show was informed, which is the thing the Act is asking for. The endpoint
refuses one that does not.

A patient id that does not exist and one the caller may not see both answer
403, so the endpoint is not a way of finding out which patients the practice
has. Every change is audited, every refusal is audited, and a clinician
reading a patient's state is audited too, because it is an access to
personal data.

The state says "not_granted" where there has been no decision, which is not
the same as a decision not to agree: a patient who has not been asked must
not look like one who said no.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

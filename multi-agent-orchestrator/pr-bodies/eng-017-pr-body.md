# ENG-017: the retention policy, built and switched off

The practice has no legal adviser yet, and cannot decide retention
numbers. So the system is built and **nothing is deleted**: the policy is
one file with two flags, and the job refuses to remove anything until both
of them are true.

    config/retention_policy.yaml

        adult_outpatient_years: 5
        adult_inpatient_years: 7
        child_until_age: 21
        prescription_years: 10
        audit_log_years: 7
        enabled: false
        legal_advisor_signed: false

The numbers are conventional practice, not law, and the file says so at
the top: they are the placeholders the system runs on while the practice
waits for an adviser, and the period for a clinical record is set by the
National Health Act 2014 and the Medical and Dental Council.

**The states.** Both flags false is the default: the job reports and
changes nothing. Enabled but not signed is refused outright -- "Refusing
to delete: legal sign-off required" -- because that is the state that
looks like the job is running and is not.

**The unit of retention is the clinical record**: the patient and their
encounters, prescriptions and appointments together, measured from their
last visit. A record is not removed in pieces.

**Two things are reported and not removed**, and the report says why: the
audit trail, because it is a hash chain whose head is published outside
the database, and the prescription documents, because they are immutable
and a document that could be edited after the fact would not be a record
of anything.

**How a record goes.** In two steps. The whole record is copied into the
trash with the moment it may be purged -- thirty days -- and the live rows
are marked with deleted_at, so the reads filter them out and a
soft-deleted record is not in the API, a search or a list. Thirty days
later the live rows go and the trash entry goes with them. Every removal,
soft or hard, is written to an immutable table with the reason and the
file the policy came from.

**The notice cannot drift from the job.** The privacy notice's "How long
we keep data" table is generated from the policy file, and a test asserts
that the table in the notice is the one the file produces. The notice
carries "DRAFT - pending legal advisor" until the numbers are confirmed.

The policy file is read strictly: an unknown key, a missing key, a value
of the wrong type or a line that is not a key and a value is an error
rather than something quietly ignored. The project has no YAML library
and one dependency, so the small subset the file uses is read by hand.

**A defect this work found in the tests.** The tests booked a slot at a
fixed moment -- 2026-10-21 at 14:00 in Europe/Berlin -- and a slot in the
past cannot be booked. The wall clock passed that moment at 12:00 UTC
today, and 37 tests that had been passing since August started failing,
including the ones the continuous integration runs. They now book a slot
tomorrow, at the same hour, computed from the clock. Nothing about the
product had changed; a test that passes until a particular hour and then
fails is a test that fails in CI.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

# The retention policy, and the job that would apply it

- **Feature:** ENG-017 — the retention policy, built and switched off
- **Status:** the machinery is complete and tested. **Nothing is deleted**, and cannot be until the
  practice's adviser confirms the periods.
- **Why it exists:** section 27(1)(e) of the Nigeria Data Protection Act 2023 requires the privacy
  notice to state how long each kind of record is kept. The notice has to say something, and what it
  says has to be what the software actually does.

## The two flags

The policy is one file, `config/retention_policy.yaml`, and it carries two flags:

```yaml
enabled: false
legal_advisor_signed: false
```

**Both have to be true before a single record is removed.** The states are:

| `enabled` | `legal_advisor_signed` | What happens |
| --- | --- | --- |
| false | false | **The default.** The job reports and changes nothing. |
| true | false | **Refused outright**: "Refusing to delete: legal sign-off required". This is the dangerous state — it looks like the job is running, and it is not. |
| true | true | The job may remove what is past its period. |

The `delete` command refuses in the first two states. The `check` command reports in all of them,
and refuses in the middle one.

**The numbers are placeholders.** The file says so at the top, in the words `TODO_LEGAL` and
"TEMPORARY placeholders", and the comment names where they came from: conventional practice — 5
years outpatient, 7 years inpatient, 6–9 general, 21 for children. They are not law. The period for
a clinical record is set by the National Health Act 2014 and the guidance of the Medical and Dental
Council of Nigeria, and the clause could not be read from the gazette scan available when this was
written — so no number is asserted as law, anywhere.

## What is kept, and for how long

| Record | Period | Rule |
| --- | --- | --- |
| the clinical record — the patient, their encounters, prescriptions and appointments together | 5 years after the last visit; until the patient reaches 21 if they were a child | `adult_outpatient_years`, `child_until_age` |
| a prescription document | 10 years after it was issued | `prescription_years` |
| the audit trail | 7 years after the entry was written | `audit_log_years` |

**The unit is the clinical record.** A record is not removed in pieces: the patient and everything
that belongs to them go together, measured from their last visit. A patient who has never been seen
has no last visit, and is not a candidate — there is no period to measure.

**Two things are reported and not removed**, and the report says why:

- **the audit trail**, because it is a hash chain: every entry links to the one before it and the
  head of the chain is published outside the database. Pruning it would break the chain that makes
  it worth anything.
- **the prescription documents**, because they are immutable: the schema refuses a change to one
  and refuses its removal, because a document that could be edited after the fact would not be a
  record of anything. The prescription the document belongs to goes with the clinical record.

## How a record goes

In two steps, and only when the flags allow it.

1. **Soft delete.** The whole record — the patient, their encounters, their prescriptions, their
   appointments — is copied into `deleted_record` with the moment it was deleted and the moment it
   may be purged. The live rows are marked with `deleted_at` and stop being served: the reads in
   `telemedicine/persistence/clinical_store.py` filter them out, so a soft-deleted record is not
   in the API, not in a search and not in a list.
2. **Hard delete.** Thirty days later the live rows are removed and the trash entry goes with them.

Thirty days is the grace period: a record taken out in error can be put back until then, and
`restore()` does it.

**Every removal is written to `deletion_audit`** — soft, hard, or restored — with the reason and the
file the policy came from. The table is append-only: the schema refuses a change to a row and
refuses its removal and its truncation, because a record of what was deleted that could be edited
afterwards would not be evidence of anything.

## The command

```bash
python3 scripts/retention.py check --dry-run     # report only
python3 scripts/retention.py check               # report, and remove if allowed
python3 scripts/retention.py delete              # remove, if allowed
```

The exit status is 0 when the command did what it was asked to do and 1 when it refused: a job that
could not do its work must not look like a job that had nothing to do.

`check --dry-run` prints "Would delete N records" and changes nothing, whatever the policy says.

## The notice and the job cannot drift apart

The privacy notice's "How long we keep data" table is **generated from the policy file** by
`policy_table_markdown()`, and a test asserts that the table in the notice is the one the file
produces. When the adviser confirms the numbers and the file changes, the notice's table changes
with it — and the notice carries the warning "DRAFT - pending legal advisor" until they are
confirmed.

## How the policy file is read

The file is YAML, and the project has **no YAML library** — it has one dependency and it is the
PostgreSQL driver. So `telemedicine/retention.py` reads the small, strict subset of YAML the
policy file uses: `key: value` lines, `#` comments, and nothing else.

It reads it **strictly**. An unknown key, a missing key, a value of the wrong type or a line that is
not a key and a value is an error, not something quietly ignored. A policy that is half-read is a
policy nobody can rely on, and the numbers in this file decide what is removed from a patient's
record.

## A defect this work found in the tests

The tests booked a slot at a fixed moment — 2026-10-21 at 14:00, in Europe/Berlin — and a slot in
the past cannot be booked. The wall clock passed that moment at 12:00 UTC, and **37 tests that had
been passing since August started failing**, including the ones the continuous integration runs.

They now book a slot tomorrow, at the same hour, computed from the clock. The fix is in five test
files. It is worth recording: a test that passes until a particular hour and then fails is a test
that fails in the continuous integration, and nothing about the product had changed.

## What is not built

- **The Essential Drugs List check.** Whether a medicine may be prescribed at all is a check against
  the list under section 39 of the National Health Act 2014. It is not built.
- **A restore command.** `restore()` exists and is tested; there is no command line for it, because
  there is no reason to restore anything while nothing is being deleted.
- **A way to prune the audit trail.** It is a hash chain, and pruning it would break the chain.

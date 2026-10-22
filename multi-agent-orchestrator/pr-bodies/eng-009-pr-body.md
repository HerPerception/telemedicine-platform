# ENG-009: the clinical records in the database, and the services stop holding them

The last records still held in dictionaries were the clinical ones, and
with them the last thing between this project and a deployment that keeps
its records.

* telemedicine/repositories.py - where the records go, and the
  implementation that keeps them in memory.
* The services hold no records any more. RecordsService and SlotService
  take a repository and ask it for what they need, and BookingService keeps
  no copy of the appointments at all: the appointments are the records of
  ENG-002, and the slot-to-appointment mapping is a question about the
  data, so the data answers it. The behaviour is unchanged - the 375 tests
  that existed before the refactor passed without being touched.
* telemedicine/persistence/clinical_store.py - the clinical records in the
  tables of ENG-001.

Two details are worth knowing. The account link lives on the clinical rows:
patient.account_ref and practitioner.account_ref hold the id of the account
the row belongs to, and the appointment, the encounter, the prescription and
the slot store the clinical id, with the account id resolved by a join.
There is one place where "which account is this patient" is written, and it
cannot disagree with itself. And the display name is derived from the name
parts, because it is a presentation of them rather than a fact of its own.

The database is now the guarantee against double-booking across instances.
The check in the service is a courtesy; the partial unique index is the
guarantee, and the store turns the database's refusal into the same
ConflictError the service raises. The test that matters starts two threads
booking the same slot on two services over one database: one is booked, one
is refused, and one active appointment is left.

The database also caught a modelling gap while this was being written: the
schema has always required a cancellation to carry a reason and a moment,
and the domain object had nowhere to put them. The appointment gained the
two fields, and the booking service records them.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

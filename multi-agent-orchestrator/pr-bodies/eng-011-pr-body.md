# ENG-011: the notification outbox, so a booking reaches both parties

The README's acceptance criteria for booking include that both parties
receive a confirmation, and nothing has ever told either of them
anything.

The MVP has no mail server, and no transport of any kind, so what can be
built honestly is the half the application is responsible for: deciding
that a message is owed, and making sure it cannot be lost.

* A message is written to the notification_outbox table when the thing
  happens, and something else sends it afterwards. A booking and its
  confirmation are then either both there or neither: if the application
  sent the mail inline, a crash between the two would leave a patient with
  a booking nobody told them about.
* The patient and the clinician are told different things. The patient is
  told their appointment has been booked; the clinician that an
  appointment has been booked for one of their patients. A message that
  says the same to both says the wrong thing to one of them.
* A message that cannot be sent is not lost. It stays queued with the
  error recorded and is tried again, until it has been tried five times,
  when it is marked failed and somebody has to look at it. A message that
  fails for ever must not be retried for ever, and must not be quietly
  dropped either.
* The delivery process claims a message with FOR UPDATE SKIP LOCKED, so
  two of them can run at once without sending the same message twice.
* db/notification_schema.sql - the outbox table.
* telemedicine/persistence/notification_store.py - the queue in the
  database.
* tests/test_notifications.py - 15 tests, including that a queued
  confirmation survives a restart.

The database found two mistakes, both the same one: the audit log's actor
column is a uuid and the system actions wrote the string "system" into
it, and the outbox's recipient is an account and so has a uuid id. An
action that was not performed by an account now has no actor, exactly as
a login against an address that has no account has none.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

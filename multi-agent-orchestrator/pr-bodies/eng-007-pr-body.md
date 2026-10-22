# ENG-007: the schema applied for the first time, a durable audit log, a shared lockout

Every pull request in this project carried the same caveat: the DDL had
never been executed, because there was no server. It turned out to be worse
than a caveat. Applying the schema to a real PostgreSQL 16.2 found three
defects, in the files every other feature depends on:

* medication_request has a composite foreign key to encounter (id,
  patient_id, practitioner_id), and that key was never declared unique.
  PostgreSQL refuses the whole file. It is declared now.
* The GiST index over schedule_slot needs the btree_gist extension, and
  only the exclusion constraint was marked as needing it. Both are marked.
* audit_log.actor_user_id is a uuid column, and the application wrote the
  string "anonymous" into it for a login against an account that does not
  exist. The actor of an unknown account is now null, and the schema says
  so.

* telemedicine/persistence/database.py - the connection, the transactions
  and the schema application. The files in db/ are the source of truth.
  They are now re-runnable, so a deployment can apply them on every start,
  and a statement that needs an extension the server does not have is
  skipped with a report that says which one.
* telemedicine/persistence/audit_store.py - the audit log in the database.
  The chain head is read and the row written in one transaction, under an
  advisory lock, so two writers cannot fork the chain. This closes SEC-06:
  the log survives a restart.
* telemedicine/persistence/lockout.py - the failed-attempt counter, in the
  auth_lockout table and in memory, behind one interface. This closes
  SEC-04: the counter is shared between instances. The service counts five
  failures and then doubles the lock, up to fifteen minutes.
* db/security_schema.sql - the lockout table.
* scripts/apply_schema.py - the command that applies the schema.
* pyproject.toml - the dependency manifest. The project gains one
  dependency, the PostgreSQL driver: there is no driver in the standard
  library and no honest way to keep a record without one. The application
  code stays standard library only.
* tests/test_persistence.py - 16 tests that need a server and are skipped
  without one, including the two that matter: four threads writing at once
  do not fork the chain, and two instances share the lockout counter.
* .github/workflows/ci.yml - a PostgreSQL service, so the persistence
  tests run in CI rather than being skipped there.
* docs/persistence-design.md and docs/reviews/remediation-status.md - the
  design, and the state of every finding of the compliance review.

Checks:

    python3 -m unittest discover -s tests -v
    python3 scripts/validate_fhir_examples.py
    python3 scripts/apply_schema.py "$DSN"

The clinical data is still in memory: the tables exist and the schema
runs, but the repositories do not use them yet. That is the next piece of
work, and it is the last big one between this project and a deployment.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*

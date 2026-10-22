# ENG-008: the accounts, the sessions and the prescription documents in the database

Three more pieces of state have the same property the lockout had: they
have to be shared between the instances of the application, and they have
to survive a restart.

* The accounts. An account created on one instance has to be known to the
  others, or a patient cannot sign in twice.
* The sessions. A session issued on one instance has to be accepted by the
  others, or a request that lands on a different instance is refused and
  the patient is asked to sign in again. This is the state that decides
  where a request may be load-balanced to.
* The prescription documents. The document is what a patient prints and
  takes to a pharmacy; it is a clinical record, and it has to outlive the
  process that rendered it.

* telemedicine/persistence/account_store.py - the accounts and the sessions
  in user_account and auth_session, satisfying the interfaces of ENG-002, so
  the service does not know whether it is talking to memory or to a
  database.
* telemedicine/persistence/document_store.py - the prescription documents in
  prescription_document.
* db/prescription_schema.sql - a body bytea column for the document, and
  the trigger now refuses a DELETE as well as an UPDATE: a prescription
  that has been printed and handed to a pharmacy must not be able to
  disappear.
* tests/test_persistence_state.py - 14 tests. The cross-instance ones
  matter: an account registered on one service is authenticated by
  another, a session issued on one service is accepted by another, a revoked
  session is refused by another, and a document written by one store is
  read by another. The token is never stored in the clear.

The clinical data is still in memory, and that is the last big piece of
work before a deployment. The test that writes a whole clinical chain -
patient, practitioner, slot, appointment, encounter, prescription - to the
database proves the relationships hold; the services do not use the tables
yet.

---

*This file was rebuilt from the commits on 2026-10-22, after the primary checkout was
re-cloned and the untracked coordination files were lost with it. The pull request
itself is on GitHub, with the body it was opened with.*
